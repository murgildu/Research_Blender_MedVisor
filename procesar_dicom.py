import bpy
import os
import subprocess
import tempfile
import time
import threading
import queue
import SimpleITK as sitk
import numpy as np
from skimage import measure
from . import visor_slicer

class MEDVISION_OT_extract_solid_brain(bpy.types.Operator):
    bl_idname = "medvision.extract_solid_brain"
    bl_label = "Extraer Cerebro (HD-BET)"
    bl_description = "Ejecuta HD-BET y FSL en segundo plano, centra la geometría y corrige la orientación"

    _timer = None
    _thread = None
    _queue = None

    def modal(self, context, event):
        if event.type == 'TIMER':
            try:
                # El hilo principal pregunta a la cola si hay novedades
                msg, error = self._queue.get_nowait()
                
                if error:
                    self.report({'ERROR'}, f"Fallo en proceso externo: {msg}")
                    self.limpiar_modal(context)
                    return {'CANCELLED'}
                elif msg == "TERMINADO":
                    # El subproceso terminó con éxito, ahora Blender asume el control seguro
                    self.finalizar_procesamiento(context)
                    self.limpiar_modal(context)
                    return {'FINISHED'}
                    
            except queue.Empty:
                # El hilo secundario sigue trabajando. Dejamos que Blender respire y repinte la UI.
                pass
                
        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        self.tiempo_inicio = time.time()
        self.ruta_archivo = bpy.path.abspath(context.scene.mri_filepath)
        self.ruta_hdbet = bpy.path.abspath(context.scene.hdbet_filepath)

        if not os.path.isfile(self.ruta_archivo) or not self.ruta_archivo.endswith('.nii.gz'):
            self.report({'ERROR'}, "Selecciona un archivo MRI válido (.nii.gz).")
            return {'CANCELLED'}

        if not os.path.isfile(self.ruta_hdbet):
            self.report({'ERROR'}, "Selecciona el ejecutable de HD-BET de tu entorno virtual.")
            return {'CANCELLED'}

        self.report({'INFO'}, "Procesando IA y FSL en segundo plano... Blender no se congelará.")
        
        # 1. Preparamos la comunicación (Queue) y el temporizador
        self._queue = queue.Queue()
        self._timer = context.window_manager.event_timer_add(0.5, window=context.window)
        context.window_manager.modal_handler_add(self)

        # 2. Lanzamos el trabajo pesado a un hilo distinto
        self._thread = threading.Thread(target=self.ejecutar_subprocesos)
        self._thread.start()
        
        return {'RUNNING_MODAL'}

    def ejecutar_subprocesos(self):
        """Esta función corre aislada en un Hilo Secundario. Puede bloquearse todo lo que necesite."""
        try:
            self.temp_dir = tempfile.gettempdir()
            self.salida_hdbet = os.path.join(self.temp_dir, "cerebro_limpio_hdbet.nii.gz")
            self.prefijo_fsl = os.path.join(self.temp_dir, "fsl_seg")

            print("Paso 1: Ejecutando HD-BET en segundo plano...")
            comando_hdbet = [self.ruta_hdbet, "-i", self.ruta_archivo, "-o", self.salida_hdbet]
            # capture_output=True evita que la consola de Windows abrume al usuario
            subprocess.run(comando_hdbet, check=True, capture_output=True)

            print("Paso 1.5: Segmentando tejidos con FSL...")
            def windows_a_wsl(ruta):
                disco, resto = os.path.splitdrive(ruta)
                return f"/mnt/{disco.lower()[0]}{resto.replace(os.sep, '/')}"
                
            wsl_entrada = windows_a_wsl(self.salida_hdbet)
            wsl_salida = windows_a_wsl(self.prefijo_fsl)
            
            comando_fsl = f"fast -o {wsl_salida} -n 3 -p {wsl_entrada}"
            comando_wsl = ["wsl", "bash", "-lc", comando_fsl]
            subprocess.run(comando_wsl, check=True, capture_output=True)

            # Avisamos al hilo principal de que hemos terminado con éxito
            self._queue.put(("TERMINADO", False))

        except subprocess.CalledProcessError as e:
            self._queue.put((f"Error de sistema operativo: {e.stderr.decode('utf-8', errors='ignore')}", True))
        except Exception as e:
            self._queue.put((str(e), True))

    def finalizar_procesamiento(self, context):
        """Esta función vuelve a ejecutarse de forma segura en el Hilo Principal de Blender."""
        print("Paso 2: Leyendo volúmenes y orientando...")
        
        mapas_fsl = {
            'PVE_0': f"{self.prefijo_fsl}_pve_0.nii.gz",
            'PVE_1': f"{self.prefijo_fsl}_pve_1.nii.gz",
            'PVE_2': f"{self.prefijo_fsl}_pve_2.nii.gz"
        }

        filtro_orientacion = sitk.DICOMOrientImageFilter()
        filtro_orientacion.SetDesiredCoordinateOrientation("RPS")

        # 1. Procesar y alinear MRI Original
        imagen_3d = sitk.ReadImage(self.salida_hdbet)
        imagen_3d = filtro_orientacion.Execute(imagen_3d)
        volumen_np = sitk.GetArrayFromImage(imagen_3d)
        espaciado = imagen_3d.GetSpacing()

        # 2. Procesar y alinear las 3 capas PVE
        volumenes_pve_dict = {}
        for clave, ruta_mapa in mapas_fsl.items():
            if os.path.exists(ruta_mapa):
                img_pve = sitk.ReadImage(ruta_mapa)
                img_pve = filtro_orientacion.Execute(img_pve)
                volumenes_pve_dict[clave] = sitk.GetArrayFromImage(img_pve)

        # Le pasamos TODO al visor 2D
        visor_slicer.guardar_volumen(volumen_np, volumenes_pve_dict)
        
        # Guardamos las dimensiones para el HUD
        context.scene["medvisor_volumen_shape"] = list(volumen_np.shape)
        context.scene.corte_axial = volumen_np.shape[0] // 2
        context.scene.corte_coronal = volumen_np.shape[1] // 2
        context.scene.corte_sagital = volumen_np.shape[2] // 2
        
        # PASO 3: Marching cubes
        print("Paso 3: Calculando geometría 3D...")
        verts, faces, normals, values = measure.marching_cubes(
            volumen_np, level=0.5,
            spacing=(espaciado[2], espaciado[1], espaciado[0])
        )

        verts = verts[:, [2, 1, 0]]
        centro_bounding_box = (np.max(verts, axis=0) + np.min(verts, axis=0)) / 2.0
        verts = verts - centro_bounding_box

        # PASO 4: Inyectar la geometría en Blender
        print("Paso 4: Generando malla en Blender...")
        mesh = bpy.data.meshes.new("MRI_Cerebro_Mesh")
        obj = bpy.data.objects.new("MRI_Cerebro", mesh)
        mesh.from_pydata(verts.tolist(), [], faces.tolist())
        mesh.update()
        context.collection.objects.link(obj)

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj

        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        with context.temp_override(area=area, region=region):
                            bpy.ops.view3d.view_selected(use_all_regions=True)

        smooth = obj.modifiers.new(name="Smooth", type='SMOOTH')
        smooth.factor = 0.5
        smooth.iterations = 10
        
        tiempo_fin = time.time()
        tiempo_total = tiempo_fin - self.tiempo_inicio
        minutos = int(tiempo_total // 60)
        segundos = tiempo_total % 60
        
        mensaje = f"Cerebro extraido correctamente en {minutos}m {segundos:.2f}s"
        print(f"--- {mensaje} ---")
        self.report({'INFO'}, mensaje)

    def limpiar_modal(self, context):
        """Elimina el temporizador cuando el trabajo ya ha terminado."""
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        self._thread = None
        self._queue = None

def register():
    try:
        bpy.utils.register_class(MEDVISION_OT_extract_solid_brain)
    except ValueError:
        bpy.utils.unregister_class(MEDVISION_OT_extract_solid_brain)
        bpy.utils.register_class(MEDVISION_OT_extract_solid_brain)

def unregister():
    try:
        bpy.utils.unregister_class(MEDVISION_OT_extract_solid_brain)
    except RuntimeError:
        pass
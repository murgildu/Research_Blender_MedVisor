import bpy
import os
import subprocess
import tempfile
import math
import time
import SimpleITK as sitk
import numpy as np
from skimage import measure
from . import visor_slicer

class MEDVISION_OT_extract_solid_brain(bpy.types.Operator):
    bl_idname = "medvision.extract_solid_brain"
    bl_label = "Extraer Cerebro (HD-BET)"
    bl_description = "Ejecuta HD-BET en segundo plano, centra la geometría y corrige la orientación anatómica"

    def execute(self, context):
        tiempo_inicio = time.time()
        
        ruta_archivo = bpy.path.abspath(context.scene.mri_filepath)
        ruta_hdbet = bpy.path.abspath(context.scene.hdbet_filepath)

        if not os.path.isfile(ruta_archivo) or not ruta_archivo.endswith('.nii.gz'):
            self.report({'ERROR'}, "Selecciona un archivo MRI válido (.nii.gz).")
            return {'CANCELLED'}

        if not os.path.isfile(ruta_hdbet):
            self.report({'ERROR'}, "Selecciona el ejecutable de HD-BET de tu entorno virtual.")
            return {'CANCELLED'}

        try:
            temp_dir = tempfile.gettempdir()
            salida_hdbet = os.path.join(temp_dir, "cerebro_limpio_hdbet.nii.gz")

            # PASO 1: Llamada a la Inteligencia Artificial (HD-BET)
            print("Paso 1: Ejecutando HD-BET en segundo plano...")
            self.report({'INFO'}, "Procesando IA...")
            
            comando = [ruta_hdbet, "-i", ruta_archivo, "-o", salida_hdbet]
            subprocess.run(comando, check=True)

            # --- PASO 1.5 - Segmentación Tisular (FSL FAST vía WSL) ---
            print("Paso 1.5: Segmentando tejidos con FSL...")
            self.report({'INFO'}, "Segmentando con FAST...")
            
            prefijo_fsl = os.path.join(temp_dir, "fsl_seg")
            
            def windows_a_wsl(ruta):
                disco, resto = os.path.splitdrive(ruta)
                return f"/mnt/{disco.lower()[0]}{resto.replace(os.sep, '/')}"
                
            wsl_entrada = windows_a_wsl(salida_hdbet)
            wsl_salida = windows_a_wsl(prefijo_fsl)
            
            comando_fsl = f"fast -o {wsl_salida} -n 3 -p {wsl_entrada}"
            comando_wsl = ["wsl", "bash", "-lc", comando_fsl]
            
            subprocess.run(comando_wsl, check=True)

            # --- PASO 2: Leer volúmenes (Original + FSL) ---
            mapas_fsl = {
                'PVE_0': f"{prefijo_fsl}_pve_0.nii.gz",
                'PVE_1': f"{prefijo_fsl}_pve_1.nii.gz",
                'PVE_2': f"{prefijo_fsl}_pve_2.nii.gz"
            }

            print("Paso 2: Leyendo volúmenes y orientando...")
            filtro_orientacion = sitk.DICOMOrientImageFilter()
            filtro_orientacion.SetDesiredCoordinateOrientation("RPS")

            # 1. Procesar y alinear MRI Original
            imagen_3d = sitk.ReadImage(salida_hdbet)
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

            # Le pasamos TODO al visor 2D empaquetado en un diccionario
            visor_slicer.guardar_volumen(volumen_np, volumenes_pve_dict)
            
            # Guardamos las dimensiones para el HUD y los cortes
            context.scene["medvisor_volumen_shape"] = list(volumen_np.shape)
            context.scene.corte_axial = volumen_np.shape[0] // 2
            context.scene.corte_coronal = volumen_np.shape[1] // 2
            context.scene.corte_sagital = volumen_np.shape[2] // 2
            
            # PASO 3: Marching cubes → generación de la malla inicial
            print("Paso 3: Calculando geometría 3D...")
            verts, faces, normals, values = measure.marching_cubes(
                volumen_np, level=0.5,
                spacing=(espaciado[2], espaciado[1], espaciado[0])
            )

            # Reordenar los ejes de NumPy (Z,Y,X) a Blender (X,Y,Z)
            verts = verts[:, [2, 1, 0]]

            # Centrar la geometría en el origen
            centro_bounding_box = (np.max(verts, axis=0) + np.min(verts, axis=0)) / 2.0
            verts = verts - centro_bounding_box

            # PASO 4: Inyectar la geometría optimizada en Blender
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

            # Post-procesado: Suavizado superficial adaptativo
            smooth = obj.modifiers.new(name="Smooth", type='SMOOTH')
            smooth.factor = 0.5
            smooth.iterations = 10
            
            # --- FINAL: Cálculos de tiempo ---
            tiempo_fin = time.time()
            tiempo_total = tiempo_fin - tiempo_inicio
            minutos = int(tiempo_total // 60)
            segundos = tiempo_total % 60
            
            mensaje = f"Cerebro extraido correctamente en {minutos}m {segundos:.2f}s"
            print(f"--- {mensaje} ---")
            self.report({'INFO'}, mensaje)
            
            return {'FINISHED'}

        except subprocess.CalledProcessError as e:
            self.report({'ERROR'}, "Fallo al ejecutar subproceso. Revisa la consola para mas detalles.")
            return {'CANCELLED'}
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Error critico: {str(e)}")
            return {'CANCELLED'}

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
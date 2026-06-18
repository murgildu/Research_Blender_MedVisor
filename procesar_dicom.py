import bpy
import os
import subprocess
import tempfile
import math
import SimpleITK as sitk
import numpy as np
from skimage import measure

class MEDVISION_OT_extract_solid_brain(bpy.types.Operator):
    bl_idname = "medvision.extract_solid_brain"
    bl_label = "Extraer Cerebro (HD-BET)"
    bl_description = "Ejecuta HD-BET en segundo plano, centra la geometría y corrige la orientación anatómica"

    def execute(self, context):
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

            # PASO 1: Llamada a la Inteligencia Artificial
            print("Paso 1: Ejecutando HD-BET en segundo plano...")
            self.report({'INFO'}, "Procesando IA...")
            
            comando = [ruta_hdbet, "-i", ruta_archivo, "-o", salida_hdbet]
            subprocess.run(comando, check=True)

            # PASO 2: Leer el resultado generado por la IA
            print("Paso 2: Leyendo volumen limpio...")
            imagen_3d = sitk.ReadImage(salida_hdbet)
            espaciado = imagen_3d.GetSpacing()
            volumen_np = sitk.GetArrayFromImage(imagen_3d)
            
            if not np.any(volumen_np):
                self.report({'WARNING'}, "La extraccion devolvio un volumen vacio.")
                return {'CANCELLED'}

            # PASO 3: Marching cubes → generación de la malla inicial
            print("Paso 3: Calculando geometría 3D...")
            verts, faces, normals, values = measure.marching_cubes(
                volumen_np, level=0.5,
                spacing=(espaciado[2], espaciado[1], espaciado[0])
            )

            # REFINAMIENTO A: Centrar la geometría en el origen (0,0,0) mediante NumPy
            # Calculamos el punto medio de la caja del volumen y se lo restamos a los vértices
            centro_bounding_box = (np.max(verts, axis=0) + np.min(verts, axis=0)) / 2.0
            verts = verts - centro_bounding_box

            # PASO 4: Inyectar la geometría optimizada en Blender
            print("Paso 4: Generando malla en Blender...")
            mesh = bpy.data.meshes.new("MRI_Cerebro_Mesh")
            obj = bpy.data.objects.new("MRI_Cerebro", mesh)
            mesh.from_pydata(verts.tolist(), [], faces.tolist())
            mesh.update()
            context.collection.objects.link(obj)

            # REFINAMIENTO B: Corregir la inversión del sistema de coordenadas médico (NIfTI vs Blender)
            # Rotamos el objeto 180 grados sobre el eje X. Al estar centrado, el pivote es perfecto.
            obj.rotation_euler = (math.radians(180), 0, 0)

            # Post-procesado: Suavizado superficial adaptativo mediante modificador nativo
            smooth = obj.modifiers.new(name="Smooth", type='SMOOTH')
            smooth.factor = 0.5
            smooth.iterations = 10
            
            self.report({'INFO'}, "Cerebro extraido, centrado y orientado correctamente")
            return {'FINISHED'}

        except subprocess.CalledProcessError as e:
            self.report({'ERROR'}, "Fallo al ejecutar HD-BET. Revisa la consola para mas detalles.")
            return {'CANCELLED'}
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Error critico: {str(e)}")
            return {'CANCELLED'}

def register():
    bpy.utils.register_class(MEDVISION_OT_extract_solid_brain)

def unregister():
    bpy.utils.unregister_class(MEDVISION_OT_extract_solid_brain)
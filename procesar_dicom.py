import bpy
import os
import SimpleITK as sitk
import numpy as np
from skimage import measure
from scipy.ndimage import binary_fill_holes

class MEDVISION_OT_extract_solid_brain(bpy.types.Operator):
    bl_idname = "medvision.extract_solid_brain"
    bl_label = "Extraer Cerebro"
    bl_description = "Aísla el cerebro usando máscara craneal + morfología"

    def execute(self, context):
        ruta_carpeta = bpy.path.abspath(context.scene.dicom_dirpath)

        if not os.path.isdir(ruta_carpeta):
            self.report({'ERROR'}, "Selecciona una carpeta válida primero.")
            return {'CANCELLED'}

        try:
            reader = sitk.ImageSeriesReader()
            dicom_names = reader.GetGDCMSeriesFileNames(ruta_carpeta)
            reader.SetFileNames(dicom_names)
            imagen_3d = reader.Execute()
            espaciado = imagen_3d.GetSpacing()

            # PASO 1: Detectar el cráneo
            print("Paso 1: Detectando cráneo...")
            mascara_hueso = sitk.BinaryThreshold(
                imagen_3d, lowerThreshold=200, upperThreshold=3000,
                insideValue=1, outsideValue=0
            )

            # PASO 2: Sellar las cuencas oculares y fugas del cráneo
            print("Paso 2: Sellando fugas del cráneo...")
            cierre = sitk.BinaryMorphologicalClosingImageFilter()
            cierre.SetKernelRadius([4, 4, 4]) 
            cierre.SetForegroundValue(1)
            hueso_sellado = cierre.Execute(mascara_hueso)

            # PASO 3: Rellenar interior slice a slice
            print("Paso 3: Rellenando interior corte a corte...")
            volumen_hueso = sitk.GetArrayFromImage(hueso_sellado)
            volumen_relleno = np.zeros_like(volumen_hueso)
            for i in range(volumen_hueso.shape[0]):
                volumen_relleno[i] = binary_fill_holes(volumen_hueso[i]).astype(np.uint8)

            # PASO 4: Restar el cráneo para quedarnos SOLO con la cavidad interior
            interior_np = (volumen_relleno - volumen_hueso).clip(0, 1).astype(np.uint8)
            interior_craneo = sitk.GetImageFromArray(interior_np)
            interior_craneo.CopyInformation(imagen_3d)

            # PASO 5: Filtrado Hounsfield estricto para el cerebro
            print("Paso 4: Aplicando filtro HU para tejido cerebral...")
            tejido_blando = sitk.BinaryThreshold(
                imagen_3d, lowerThreshold=20, upperThreshold=80,
                insideValue=1, outsideValue=0
            )

            # Cruzamos el tejido blando con la cavidad interior sellada
            cerebro_final = sitk.And(tejido_blando, interior_craneo)
            volumen_np = sitk.GetArrayFromImage(cerebro_final)
            
            if not np.any(volumen_np):
                self.report({'WARNING'}, "El filtrado borró todo.")
                return {'CANCELLED'}

            # Marching cubes → malla 3D
            print("Calculando geometría 3D...")
            verts, faces, normals, values = measure.marching_cubes(
                volumen_np, level=0.5,
                spacing=(espaciado[2], espaciado[1], espaciado[0])
            )

            # Inyectar en Blender
            print("Generando malla en Blender...")
            mesh = bpy.data.meshes.new("DICOM_Cerebro_Mesh")
            obj = bpy.data.objects.new("DICOM_Cerebro", mesh)
            mesh.from_pydata(verts.tolist(), [], faces.tolist())
            mesh.update()
            context.collection.objects.link(obj)

            # Suavizado con modifier
            print("Aplicando suavizado...")
            smooth = obj.modifiers.new(name="Smooth", type='SMOOTH')
            smooth.factor = 0.5
            smooth.iterations = 10
            
            self.report({'INFO'}, "¡Cerebro extraído correctamente!")
            return {'FINISHED'}

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Error: {str(e)}")
            return {'CANCELLED'}

def register():
    bpy.utils.register_class(MEDVISION_OT_extract_solid_brain)

def unregister():
    bpy.utils.unregister_class(MEDVISION_OT_extract_solid_brain)
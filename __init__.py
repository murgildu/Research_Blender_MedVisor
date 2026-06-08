bl_info = {
    "name": "MedVision DICOM",
    "author": "Miriam Rodriguez",
    "version": (1, 0),
    "blender": (3, 6, 0),
    "location": "Workspace MedVision",
    "description": "Procesamiento medico y extraccion de modelos desde DICOM",
    "category": "3D View",
}

import bpy
from . import procesar_dicom
from . import paneles_ui

def limpiar_escena_inicial():
    """Borra escena por defecto si existen."""
    objetos_a_borrar = ["Cube", "Camera", "Light"]
    for nombre in objetos_a_borrar:
        obj = bpy.data.objects.get(nombre)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)

def crear_workspace_medvision():
    """Crea el workspace MedVision si no existe."""
    nombre = "MedVision"
    if nombre not in bpy.data.workspaces:
        ws_base = bpy.data.workspaces[0]
        bpy.ops.workspace.duplicate({'workspace': ws_base})
        nuevo_ws = bpy.data.workspaces[-1]
        nuevo_ws.name = nombre

@bpy.app.handlers.persistent
def handler_inicio(dummy):
    limpiar_escena_inicial()
    crear_workspace_medvision()

def register():
    procesar_dicom.register()
    paneles_ui.register()
    bpy.types.Scene.dicom_dirpath = bpy.props.StringProperty(
        name="Carpeta DICOM",
        subtype='DIR_PATH'
    )
    # Ejecutar al cargar cualquier archivo .blend
    bpy.app.handlers.load_post.append(handler_inicio)
    # Ejecutar también ahora mismo al activar el addon
    if bpy.context.scene:
        limpiar_escena_inicial()
        crear_workspace_medvision()

def unregister():
    if handler_inicio in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(handler_inicio)
    del bpy.types.Scene.dicom_dirpath
    paneles_ui.unregister()
    procesar_dicom.unregister()

if __name__ == "__main__":
    register()
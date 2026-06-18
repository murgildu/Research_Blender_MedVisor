bl_info = {
    "name": "MedVision",
    "author": "Miriam Rodriguez",
    "version": (1, 1),
    "blender": (3, 6, 0),
    "location": "Workspace MedVision",
    "description": "Extracción de cerebro desde MRI (.nii.gz) usando IA (HD-BET)",
    "category": "3D View",
}

import bpy
from . import procesar_dicom
from . import paneles_ui

# ─── Estado global ────────────────────────────────────────────────────────────
_DIVISION_HECHA = False
_HANDLER_ACTIVO = False   # Evita añadir el handler más de una vez


def limpiar_escena_inicial():
    """Borra objetos por defecto si existen."""
    for nombre in ["Cube", "Camera", "Light"]:
        obj = bpy.data.objects.get(nombre)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)


# ─── Workspace ────────────────────────────────────────────────────────────────

def crear_workspace_medvision():
    """Crea el workspace MedVision si no existe, sin dividir áreas."""
    nombre = "MedVision"
    if nombre in bpy.data.workspaces:
        return

    ws_base = bpy.data.workspaces.get("Layout") or bpy.context.window.workspace
    pestañas_existentes = {ws.name for ws in bpy.data.workspaces}
    
    with bpy.context.temp_override(workspace=ws_base):
        bpy.ops.workspace.duplicate()
    
    # Renombramos el nuevo workspace creado
    for ws in bpy.data.workspaces:
        if ws.name not in pestañas_existentes:
            ws.name = nombre
            bpy.context.window.workspace = ws # Opcional: saltar al nuevo workspace
            break

def register():
    procesar_dicom.register()
    paneles_ui.register()
    
    bpy.types.Scene.mri_filepath = bpy.props.StringProperty(name="Archivo MRI", subtype='FILE_PATH')
    bpy.types.Scene.hdbet_filepath = bpy.props.StringProperty(name="Ruta HD-BET", subtype='FILE_PATH')
    
    # Ejecución única para asegurar el Workspace
    bpy.app.timers.register(crear_workspace_medvision, first_interval=1.0)

def unregister():
    del bpy.types.Scene.mri_filepath
    del bpy.types.Scene.hdbet_filepath
    paneles_ui.unregister()
    procesar_dicom.unregister()


if __name__ == "__main__":
    register()
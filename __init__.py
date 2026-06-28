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
from . import visor_slicer


def limpiar_escena_inicial():
    for nombre in ["Cube", "Camera", "Light"]:
        obj = bpy.data.objects.get(nombre)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)


def _configurar_entorno():
    """
    Timer: una vez que el workspace MedVision existe, llama al operador
    que ya configura quad view + HUD médico.
    """
    ws = bpy.data.workspaces.get("MedVision")
    if ws is None:
        return None

    # Buscamos una ventana que esté mostrando MedVision para el override
    window = None
    for win in bpy.context.window_manager.windows:
        if win.workspace == ws:
            window = win
            break

    # Si ninguna ventana muestra MedVision aún, reintentamos en 0.3s
    if window is None:
        return 0.3

    # Buscamos un área VIEW_3D en ese workspace
    screen = window.screen
    area = next((a for a in screen.areas if a.type == 'VIEW_3D'), None)
    if area is None:
        return 0.3

    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if region is None:
        return 0.3

    with bpy.context.temp_override(window=window, screen=screen,
                                   area=area, region=region):
        bpy.ops.medvision.setup_slicer_view()

    return None  # No repetir


def _crear_workspace_medvision():
    """
    Timer: crea el workspace MedVision y encadena _configurar_entorno.
    """
    nombre = "MedVision"

    if nombre not in bpy.data.workspaces:
        ws_base = bpy.data.workspaces.get("Layout") or bpy.context.window.workspace
        existentes = {ws.name for ws in bpy.data.workspaces}

        with bpy.context.temp_override(workspace=ws_base):
            bpy.ops.workspace.duplicate()

        for ws in bpy.data.workspaces:
            if ws.name not in existentes:
                ws.name = nombre
                break

    # Damos tiempo a Blender para renderizar el workspace antes de tocar sus áreas
    bpy.app.timers.register(_configurar_entorno, first_interval=0.8)
    return None  # No repetir


def register():
    procesar_dicom.register()
    paneles_ui.register()

    bpy.types.Scene.mri_filepath = bpy.props.StringProperty(
        name="Archivo MRI", subtype='FILE_PATH')
    bpy.types.Scene.hdbet_filepath = bpy.props.StringProperty(
        name="Ruta HD-BET", subtype='FILE_PATH')

    bpy.types.Scene.corte_plano = bpy.props.EnumProperty(
        name="Plano de Corte",
        items=[('AXIAL', "Axial", ""), ('SAGITAL', "Sagital", ""), ('CORONAL', "Coronal", "")],
        default='AXIAL',
        update=visor_slicer.actualizar_corte
    )
    bpy.types.Scene.corte_profundidad = bpy.props.IntProperty(
        name="Profundidad",
        default=0, min=0, max=256,
        update=visor_slicer.actualizar_corte
    )

    bpy.app.timers.register(_crear_workspace_medvision, first_interval=1.0)


def unregister():
    for fn in (_crear_workspace_medvision, _configurar_entorno):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)

    # Limpia el HUD si sigue activo
    if "hud_medico_handle" in bpy.app.driver_namespace:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(
                bpy.app.driver_namespace["hud_medico_handle"], 'WINDOW')
            del bpy.app.driver_namespace["hud_medico_handle"]
        except Exception:
            pass

    del bpy.types.Scene.mri_filepath
    del bpy.types.Scene.hdbet_filepath

    if hasattr(bpy.types.Scene, "corte_plano"):
        del bpy.types.Scene.corte_plano
    if hasattr(bpy.types.Scene, "corte_profundidad"):
        del bpy.types.Scene.corte_profundidad
    
    visor_slicer.unregister()
    paneles_ui.unregister()
    procesar_dicom.unregister()


if __name__ == "__main__":
    register()
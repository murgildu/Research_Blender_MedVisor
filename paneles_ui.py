import bpy
import blf
import math

def dibujar_nombres_medicos():
    if not bpy.context.area or bpy.context.area.type != 'VIEW_3D': return
    rv3d = bpy.context.region_data
    if not rv3d: return
    
    texto = "3D (Perspectiva)" 
    if rv3d.view_perspective == 'ORTHO':
        rot = rv3d.view_rotation.to_euler()
        rx_abs = abs(round(math.degrees(rot.x)))
        rz_abs = abs(round(math.degrees(rot.z)))
        if rx_abs == 0 or rx_abs == 180: texto = "AXIAL (Top)"
        elif rx_abs == 90 and (rz_abs == 0 or rz_abs == 180): texto = "CORONAL (Front)"
        elif rx_abs == 90 and (rz_abs == 90 or rz_abs == 270): texto = "SAGITAL (Right)"

    font_id = 0
    try: blf.size(font_id, 24) 
    except: blf.size(font_id, 24, 72)
    blf.color(font_id, 0.0, 0.0, 0.0, 1.0)
    blf.position(font_id, 22, 18, 0)
    blf.draw(font_id, texto)
    blf.color(font_id, 1.0, 0.65, 0.1, 1.0) 
    blf.position(font_id, 20, 20, 0)
    blf.draw(font_id, texto)

class MEDVISION_OT_setup_slicer_view(bpy.types.Operator):
    bl_idname = "medvision.setup_slicer_view"
    bl_label = "Configurar Entorno (4 Vistas)"
    bl_description = "Aplica las vistas ortogonales y el HUD medico"

    def execute(self, context):
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        with bpy.context.temp_override(area=area, region=region):
                            if not area.spaces.active.region_quadviews:
                                bpy.ops.screen.region_quadview()
                            bpy.ops.view3d.view_all(center=True)
                espacio = area.spaces.active
                espacio.shading.type = 'SOLID'
                espacio.show_gizmo = False
                espacio.show_region_header = True

        if "hud_medico_handle" in bpy.app.driver_namespace:
            try: bpy.types.SpaceView3D.draw_handler_remove(bpy.app.driver_namespace["hud_medico_handle"], 'WINDOW')
            except: pass

        nuevo_handle = bpy.types.SpaceView3D.draw_handler_add(dibujar_nombres_medicos, (), 'WINDOW', 'POST_PIXEL')
        bpy.app.driver_namespace["hud_medico_handle"] = nuevo_handle
        
        return {'FINISHED'}

# ---- PANEL PRINCIPAL ----
class MEDVISION_PT_main_panel(bpy.types.Panel):
    bl_label = "MedVision UI"
    bl_idname = "MEDVISION_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MedVision_Solid' 

    def draw(self, context):
        layout = self.layout
        
        layout.use_property_split = True
        layout.use_property_decorate = False
        
        col = layout.column(align=True)
        
        try:
            col.prop(context.scene, "mri_filepath")
            col.prop(context.scene, "hdbet_filepath") # NUEVO
        except Exception as e:
            col.label(text=f"Error: {str(e)}", icon='ERROR')
        
        col.separator()
        col.operator("medvision.setup_slicer_view", icon='WINDOW', text="Configurar Entorno")
        col.operator("medvision.extract_solid_brain", icon='MESH_ICOSPHERE', text="Extraer Cerebro")

classes = (MEDVISION_OT_setup_slicer_view, MEDVISION_PT_main_panel)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
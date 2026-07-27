import bpy
import blf
import math
from . import visor_slicer

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
            try: 
                bpy.types.SpaceView3D.draw_handler_remove(bpy.app.driver_namespace["hud_medico_handle"], 'WINDOW')
            except ValueError: 
                pass

        nuevo_handle = bpy.types.SpaceView3D.draw_handler_add(dibujar_nombres_medicos, (), 'WINDOW', 'POST_PIXEL')
        bpy.app.driver_namespace["hud_medico_handle"] = nuevo_handle
        
        return {'FINISHED'}

class MEDVISION_OT_modal_zoom(bpy.types.Operator):
    bl_idname = "medvision.modal_zoom"
    bl_label = "Navegación 2D"
    bl_description = "Rueda para Zoom, Clic central para desplazar"
    bl_options = {'REGISTER', 'UNDO'}

    def modal(self, context, event):
        if event.type == 'ESC':
            self.report({'INFO'}, "Navegación 2D desactivada")
            visor_slicer._crosshair_active = False 
            self.report({'INFO'}, "Navegación 2D desactivada")
            return {'CANCELLED'}

        x, y = event.mouse_x, event.mouse_y
        
        # Detectar en qué ventana estamos
        active_region = None
        for region in context.area.regions:
            if region.type == 'WINDOW':
                if region.x <= x <= region.x + region.width and region.y <= y <= region.y + region.height:
                    active_region = region
                    break
        
        rv3d = active_region.data if active_region else None
        is_2d_view = False
        vista = None
        
        if rv3d and rv3d.view_perspective == 'ORTHO':
            is_2d_view = True
            from .visor_slicer import _detectar_vista
            vista = _detectar_vista(rv3d)

        # 1. GESTIONAR EL DESPLAZAMIENTO (PAN)
        if event.type == 'MIDDLEMOUSE':
            if event.value == 'PRESS' and is_2d_view:
                self.is_panning = True
                self.active_view = vista
                self.last_mouse_x = x
                self.last_mouse_y = y
                return {'RUNNING_MODAL'}
            elif event.value == 'RELEASE':
                if self.is_panning:
                    self.is_panning = False
                    self.active_view = None
                    return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE' and getattr(self, 'is_panning', False) and self.active_view:
            dx = x - self.last_mouse_x
            dy = y - self.last_mouse_y
            
            if self.active_view == 'AXIAL':
                context.scene.offset_x_axial += dx
                context.scene.offset_y_axial += dy
            elif self.active_view == 'CORONAL':
                context.scene.offset_x_coronal += dx
                context.scene.offset_y_coronal += dy
            elif self.active_view == 'SAGITAL':
                context.scene.offset_x_sagital += dx
                context.scene.offset_y_sagital += dy
                
            self.last_mouse_x = x
            self.last_mouse_y = y
            return {'RUNNING_MODAL'}

        # 2. GESTIONAR EL ZOOM
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            if is_2d_view and vista:
                step = 0.25 
                modificador = step if event.type == 'WHEELUPMOUSE' else -step
                
                if vista == 'AXIAL':
                    context.scene.zoom_axial = max(0.1, min(10.0, context.scene.zoom_axial + modificador))
                elif vista == 'CORONAL':
                    context.scene.zoom_coronal = max(0.1, min(10.0, context.scene.zoom_coronal + modificador))
                elif vista == 'SAGITAL':
                    context.scene.zoom_sagital = max(0.1, min(10.0, context.scene.zoom_sagital + modificador))
                return {'RUNNING_MODAL'}
            
        # 3. GESTIONAR CLIC PARA SINCRONIZAR VISTAS     
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and is_2d_view:
            rect = visor_slicer._current_img_rect[vista]
            
            mouse_region_x = x - active_region.x
            mouse_region_y = y - active_region.y
            
            # Evitar errores matemáticos
            if rect['pw'] > 0 and rect['ph'] > 0:
                # Calcular el porcentaje exacto (0.0 a 1.0) dentro de la imagen
                rel_x = (mouse_region_x - rect['x0']) / rect['pw']
                rel_y = (mouse_region_y - rect['y0']) / rect['ph']
                
                # Solo actualizar si hemos hecho clic DENTRO de la imagen
                if 0.0 <= rel_x <= 1.0 and 0.0 <= rel_y <= 1.0:
                    visor_slicer._crosshair_active = True 
                    
                    vol_shape = context.scene.get("medvisor_volumen_shape", [256, 256, 256])
                    
                    # Usamos max(1, ...) para evitar divisiones por cero o índices fuera de rango
                    max_z = max(1, vol_shape[0] - 1)
                    max_y = max(1, vol_shape[1] - 1)
                    max_x = max(1, vol_shape[2] - 1)
                    
                    # SIMETRÍA EXACTA CON EL DIBUJO (Usamos 1.0 - rel_y para el eje vertical)
                    if vista == 'AXIAL':
                        context.scene.corte_sagital = int(rel_x * max_x)
                        context.scene.corte_coronal = int((1.0 - rel_y) * max_y)
                    elif vista == 'CORONAL':
                        context.scene.corte_sagital = int(rel_x * max_x)
                        context.scene.corte_axial   = int((1.0 - rel_y) * max_z)
                    elif vista == 'SAGITAL':
                        context.scene.corte_coronal = int(rel_x * max_y)
                        context.scene.corte_axial   = int((1.0 - rel_y) * max_z)
                    
                    # Forzar redibujado de todas las ventanas 3D
                    for area in context.screen.areas:
                        if area.type == 'VIEW_3D':
                            area.tag_redraw()
            
            return {'RUNNING_MODAL'}
        
        return {'PASS_THROUGH'}
        

    def invoke(self, context, event):
        if context.area.type == 'VIEW_3D':
            self.is_panning = False
            self.active_view = None
            self.last_mouse_x = event.mouse_x
            self.last_mouse_y = event.mouse_y
            context.window_manager.modal_handler_add(self)
            self.report({'INFO'}, "Navegación Interactiva ACTIVADA (ESC para detener)")
            return {'RUNNING_MODAL'}
        return {'CANCELLED'}

class MEDVISION_OT_reset_view(bpy.types.Operator):
    bl_idname = "medvision.reset_view"
    bl_label = "Centrar Vistas"
    bl_description = "Restaura el zoom y la posición al centro"
    bl_options = {'REGISTER', 'UNDO'} # Añade esto para que sea seguro y permita deshacer

    def execute(self, context):
        context.scene.zoom_axial = 1.0
        context.scene.zoom_coronal = 1.0
        context.scene.zoom_sagital = 1.0
        context.scene.offset_x_axial = 0.0
        context.scene.offset_y_axial = 0.0
        context.scene.offset_x_coronal = 0.0
        context.scene.offset_y_coronal = 0.0
        context.scene.offset_x_sagital = 0.0
        context.scene.offset_y_sagital = 0.0
        
        visor_slicer._crosshair_active = False
        
        # Forzar refresco de pantalla para que la imagen vuelva al centro inmediatamente
        if context.area:
            context.area.tag_redraw()
            
        return {'FINISHED'}
    
class MEDVISION_PT_main_panel(bpy.types.Panel):
    bl_label = "MedVision Control"
    bl_idname = "MEDVISION_PT_main_panel"
    bl_space_type = 'VIEW_3D'    # Debe estar en el área 3D
    bl_region_type = 'UI'        # Región de herramientas
    bl_category = 'MedVision'    # Nombre de la pestaña en la parte inferior

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.prop(context.scene, "mri_filepath")
        col.prop(context.scene, "hdbet_filepath")
        col.separator()
        col.operator("medvision.extract_solid_brain", text="Extraer Cerebro")

        layout.separator()
        
        box = layout.box()
        box.label(text="Visor Slicer 2D", icon='IMAGE_BACKGROUND')

        box.prop(context.scene, "tejido_visualizado", text="Capa FSL")
        box.separator()

        box.prop(context.scene, "corte_axial", text="Axial (Top)")
        box.prop(context.scene, "corte_coronal", text="Coronal (Front)")
        box.prop(context.scene, "corte_sagital", text="Sagital (Right)")

        layout.separator()
        
        # Fila compacta con el botón de navegación y el de recentrar vistas
        row = layout.row(align=True)
        row.operator("medvision.modal_zoom", text="Activar Navegación", icon='MOUSE_MMB_SCROLL')
        row.operator("medvision.reset_view", text="", icon='FILE_REFRESH')

classes = (MEDVISION_OT_reset_view, MEDVISION_OT_setup_slicer_view, MEDVISION_OT_modal_zoom, MEDVISION_PT_main_panel)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
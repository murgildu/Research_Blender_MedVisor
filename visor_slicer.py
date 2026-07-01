import bpy
import numpy as np
import gpu
from gpu_extras.batch import batch_for_shader

_volumen_global = None
_draw_handle    = None

_lonchas  = {'AXIAL': None, 'CORONAL': None, 'SAGITAL': None}
_textures = {'AXIAL': None, 'CORONAL': None, 'SAGITAL': None}
_crosshair_pos = {'AXIAL': [0.5, 0.5], 'CORONAL': [0.5, 0.5], 'SAGITAL': [0.5, 0.5]}
_crosshair_active = False
_current_img_rect = {
    'AXIAL': {'x0': 0, 'y0': 0, 'pw': 1, 'ph': 1},
    'CORONAL': {'x0': 0, 'y0': 0, 'pw': 1, 'ph': 1},
    'SAGITAL': {'x0': 0, 'y0': 0, 'pw': 1, 'ph': 1}
}

def _detectar_vista(rv3d):
    if rv3d is None:
        return None

    vista = getattr(rv3d, 'view', None)

    if vista in ('TOP', 'BOTTOM'):
        return 'AXIAL'
    if vista in ('FRONT', 'BACK'):
        return 'CORONAL'
    if vista in ('RIGHT', 'LEFT'):
        return 'SAGITAL'

    if rv3d.view_perspective == 'ORTHO':
        import math
        rot  = rv3d.view_rotation.to_euler()
        rx   = abs(round(math.degrees(rot.x)))
        rz   = abs(round(math.degrees(rot.z)))
        if rx in (0, 180):
            return 'AXIAL'
        if rx == 90 and rz in (0, 180):
            return 'CORONAL'
        if rx == 90 and rz in (90, 270):
            return 'SAGITAL'

    return None

def _transformar_loncha(plano: str, loncha: np.ndarray) -> np.ndarray:
    if plano == 'AXIAL':
        return np.flipud(loncha)
    if plano == 'CORONAL':
        return np.flipud(np.rot90(loncha, k=2))
    if plano == 'SAGITAL':
        return np.fliplr(np.rot90(loncha.T, k=3))
    return loncha

def _actualizar_textura(plano: str, loncha: np.ndarray):
    global _textures
    vmin, vmax = loncha.min(), loncha.max()
    datos = ((loncha - vmin) / (vmax - vmin)).astype(np.float32) if vmax > vmin else np.zeros_like(loncha, dtype=np.float32)

    h, w = datos.shape
    alfa = (datos > 0.02).astype(np.float32)
    rgba = np.stack([datos, datos, datos, alfa], axis=-1)

    buf = gpu.types.Buffer('FLOAT', h * w * 4, rgba.flatten().tolist())
    _textures[plano] = gpu.types.GPUTexture((w, h), format='RGBA32F', data=buf)

def guardar_volumen(volumen_np: np.ndarray):
    """Guarda el volumen y pre-calcula las tres vistas al 50 % """
    global _volumen_global, _lonchas

    _volumen_global = volumen_np.astype(np.float32)

    z_mid = volumen_np.shape[0] // 2
    y_mid = volumen_np.shape[1] // 2
    x_mid = volumen_np.shape[2] // 2

    for plano, raw in (
        ('AXIAL',   volumen_np[z_mid, :, :]),
        ('CORONAL', volumen_np[:, y_mid, :]),
        ('SAGITAL', volumen_np[:, :, x_mid]),
    ):
        loncha = _transformar_loncha(plano, raw)
        _lonchas[plano] = loncha
        _actualizar_textura(plano, loncha)

    activar_visor()

def _actualizar_corte_generico(context, plano, profundidad):
    global _volumen_global, _lonchas
    if _volumen_global is None:
        return

    volumen_np  = _volumen_global

    limites = {
        'AXIAL':   volumen_np.shape[0] - 1,
        'CORONAL': volumen_np.shape[1] - 1,
        'SAGITAL': volumen_np.shape[2] - 1,
    }
    max_limite = limites.get(plano, 0)

    # Clampeamos el valor de seguridad
    profundidad = min(profundidad, max_limite)

    try:
        if plano == 'AXIAL':
            raw = volumen_np[profundidad, :, :]
        elif plano == 'CORONAL':
            raw = volumen_np[:, profundidad, :]
        elif plano == 'SAGITAL':
            raw = volumen_np[:, :, profundidad]
        else:
            return
    except IndexError:
        return

    loncha = _transformar_loncha(plano, raw)
    _lonchas[plano] = loncha
    _actualizar_textura(plano, loncha)
    activar_visor()

    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

def forzar_redibujado(self, context):
    """Refresca la pantalla inmediatamente al mover el slider de zoom"""
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

def actualizar_corte_axial(self, context):
    _actualizar_corte_generico(context, 'AXIAL', self.corte_axial)

def actualizar_corte_coronal(self, context):
    _actualizar_corte_generico(context, 'CORONAL', self.corte_coronal)

def actualizar_corte_sagital(self, context):
    _actualizar_corte_generico(context, 'SAGITAL', self.corte_sagital)

def activar_visor():
    """Registra el draw handler y re-registra el HUD de texto encima."""
    global _draw_handle
    if _draw_handle is None:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            _dibujar_slice, (), 'WINDOW', 'POST_PIXEL'
        )

    if "hud_medico_handle" in bpy.app.driver_namespace:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(
                bpy.app.driver_namespace["hud_medico_handle"], 'WINDOW'
            )
        except Exception:
            pass
        from . import paneles_ui
        nuevo_handle = bpy.types.SpaceView3D.draw_handler_add(
            paneles_ui.dibujar_nombres_medicos, (), 'WINDOW', 'POST_PIXEL'
        )
        bpy.app.driver_namespace["hud_medico_handle"] = nuevo_handle


def _dibujar_slice():
    global _textures, _lonchas, _crosshair_pos, _crosshair_active

    ctx = bpy.context
    if not ctx.area or ctx.area.type != 'VIEW_3D':
        return
    rv3d = ctx.region_data
    if not rv3d:
        return

    view_type = _detectar_vista(rv3d)
    if view_type is None:
        return  # Vista perspectiva: no pintar

    region = ctx.region
    rw, rh = region.width, region.height

    # 1. Fondo opaco
    try:
        tema_bg = ctx.preferences.themes[0].view_3d.space.gradients.high_gradient
        color_fondo = (tema_bg[0], tema_bg[1], tema_bg[2], 1.0)
    except AttributeError:
        color_fondo = (0.11, 0.11, 0.11, 1.0)

    verts_bg   = ((0, 0), (rw, 0), (rw, rh), (0, rh))
    indices_bg = ((0, 1, 2), (0, 2, 3))

    try:
        shader_bg = gpu.shader.from_builtin('UNIFORM_COLOR')
    except Exception:
        shader_bg = gpu.shader.from_builtin('2D_UNIFORM_COLOR')

    batch_bg = batch_for_shader(shader_bg, 'TRIS', {"pos": verts_bg}, indices=indices_bg)
    shader_bg.bind()
    shader_bg.uniform_float("color", color_fondo)
    batch_bg.draw(shader_bg)

    # 2. Imagen 2D
    tex    = _textures[view_type]
    loncha = _lonchas[view_type]
    if tex is None or loncha is None:
        return

    h_img, w_img = loncha.shape
    ratio = w_img / h_img if h_img > 0 else 1.0
    if rw / rh > ratio:
        ph, pw = rh, int(rh * ratio)
    else:
        pw, ph = rw, int(rw / ratio)

    zoom_factor = 1.0
    offset_x = 0.0
    offset_y = 0.0
    
    if view_type == 'AXIAL':
        zoom_factor = ctx.scene.zoom_axial
        offset_x = ctx.scene.offset_x_axial
        offset_y = ctx.scene.offset_y_axial
    elif view_type == 'CORONAL':
        zoom_factor = ctx.scene.zoom_coronal
        offset_x = ctx.scene.offset_x_coronal
        offset_y = ctx.scene.offset_y_coronal
    elif view_type == 'SAGITAL':
        zoom_factor = ctx.scene.zoom_sagital
        offset_x = ctx.scene.offset_x_sagital
        offset_y = ctx.scene.offset_y_sagital

    pw = int(pw * zoom_factor)
    ph = int(ph * zoom_factor)

    # Sumamos el offset matemático para mover la imagen
    x0 = (rw - pw) // 2 + int(offset_x)
    y0 = (rh - ph) // 2 + int(offset_y)
    x1 = x0 + pw
    y1 = y0 + ph

    _current_img_rect[view_type] = {'x0': x0, 'y0': y0, 'pw': pw, 'ph': ph}

    try:
        shader_img = gpu.shader.from_builtin('IMAGE')
    except Exception:
        shader_img = gpu.shader.from_builtin('2D_IMAGE')

    batch_img = batch_for_shader(
        shader_img, 'TRIS',
        {
            "pos":      ((x0, y0), (x1, y0), (x1, y1), (x0, y1)),
            "texCoord": ((0, 0),   (1, 0),   (1, 1),   (0, 1)),
        },
        indices=((0, 1, 2), (0, 2, 3)),
    )

    gpu.state.blend_set('ALPHA')
    shader_img.bind()
    shader_img.uniform_sampler("image", tex)
    batch_img.draw(shader_img)
    gpu.state.blend_set('NONE')

    # --- NUEVA LÓGICA DE CRUZ SINCRONIZADA ---
    if _crosshair_active:
        # 1. Recuperamos las dimensiones del volumen
        vol_shape = ctx.scene.get("medvisor_volumen_shape", [256, 256, 256])
        
        # 2. Leemos la FUENTE DE VERDAD (los cortes absolutos)
        c_ax = ctx.scene.corte_axial
        c_cor = ctx.scene.corte_coronal
        c_sag = ctx.scene.corte_sagital
        
        # 3. Convertimos los cortes a porcentajes relativos (0.0 a 1.0)
        rz = c_ax / vol_shape[0] if vol_shape[0] > 0 else 0.5
        ry = c_cor / vol_shape[1] if vol_shape[1] > 0 else 0.5
        rx = c_sag / vol_shape[2] if vol_shape[2] > 0 else 0.5
        
        # 4. Asignamos qué porcentaje usa cada vista
        if view_type == 'AXIAL':
            cx, cy = rx, 1.0 - ry      # Comparte X (Sagital) e Y (Coronal)
        elif view_type == 'CORONAL':
            cx, cy = rx, rz      # Comparte X (Sagital) y Z (Axial)
        elif view_type == 'SAGITAL':
            cx, cy = ry, rz      # Comparte Y (Coronal) y Z (Axial)
        else:
            cx, cy = 0.5, 0.5

        # 5. Calculamos los píxeles en pantalla
        line_x = x0 + (cx * pw)
        line_y = y0 + (cy * ph)
        
        verts_line = (
            (x0, line_y), (x1, line_y), # Línea Horizontal
            (line_x, y0), (line_x, y1)  # Línea Vertical
        )
        indices_line = ((0, 1), (2, 3))
        
        try:
            shader_line = gpu.shader.from_builtin('UNIFORM_COLOR')
        except:
            shader_line = gpu.shader.from_builtin('2D_UNIFORM_COLOR')
            
        batch_line = batch_for_shader(shader_line, 'LINES', {"pos": verts_line}, indices=indices_line)
        
        shader_line.bind()
        shader_line.uniform_float("color", (1.0, 0.0, 0.0, 0.8)) # Rojo
        batch_line.draw(shader_line)

def unregister():
    global _volumen_global, _lonchas, _textures, _draw_handle
    if _draw_handle is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        except Exception:
            pass
        _draw_handle = None
    _volumen_global = None
    _lonchas  = {'AXIAL': None, 'CORONAL': None, 'SAGITAL': None}
    _textures = {'AXIAL': None, 'CORONAL': None, 'SAGITAL': None}
import bpy
import numpy as np
import gpu
from gpu_extras.batch import batch_for_shader

_volumen_global = None
_draw_handle    = None

_lonchas  = {'AXIAL': None, 'CORONAL': None, 'SAGITAL': None}
_textures = {'AXIAL': None, 'CORONAL': None, 'SAGITAL': None}

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
    global _textures, _lonchas

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

    x0, y0 = (rw - pw) // 2, (rh - ph) // 2
    x1, y1 = x0 + pw, y0 + ph

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
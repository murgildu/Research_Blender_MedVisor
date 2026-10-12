#!/usr/bin/env python3
"""
Convertidor masivo DICOM -> NIfTI para el pipeline MedVision (estructura ADNI).

Estructura de entrada esperada (la que descarga ADNI):

    ADNI/<sujeto>/<descripcion_serie>/<AAAA-MM-DD_hh_mm_ss.0>/<ImageID>/*.dcm

Qué hace, respecto a la versión anterior:
  - Convierte TODAS las series T1 de cada sujeto (no solo la primera que encuentra).
  - Nombra los archivos con sujeto y sesión (la fecha), compatible con BIDS:
        sub-002S0619_ses-20060601_T1w.nii.gz
    (si hay varias series el mismo día se añade _run-01, _run-02...).
  - Usa dcm2niix (conversor de referencia, corrige la inclinación del gantry y
    genera el .json BIDS que usa el pipeline). dicom2nifti queda como alternativa.
  - Completa el .json con SeriesDescription y AcquisitionDate (sacados de la ruta)
    por si dcm2niix los omite.
  - Comprueba la cabecera de cada NIfTI (tamaño, vóxel, orientación, ortogonalidad).
  - No sobrescribe lo ya convertido (usa --forzar para rehacerlo).
  - Escribe un conversion_manifest.csv con lo convertido.

Requisitos:
  - dcm2niix en el PATH (https://github.com/rordenlab/dcm2niix) o indicado con --dcm2niix.
  - nibabel (opcional, para la comprobación de cabecera).
  - dicom2nifti solo si usas --motor dicom2nifti.

Ejemplos:
  python convertidor_masivo.py --dry-run
  python convertidor_masivo.py -i C:\\datos\\ADNI -o C:\\datos\\salida
  python convertidor_masivo.py --patron "mp.?rage" --forzar
"""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ORIGEN_POR_DEFECTO = r"C:\Users\Miriam\Downloads\siena\ADNI"
DESTINO_POR_DEFECTO = r"C:\Users\Miriam\Downloads\siena\salida"

# Series que se consideran T1 (se busca en toda la ruta relativa, sin distinguir mayúsculas)
PATRON_T1_POR_DEFECTO = r"mp.?rage|spgr|t1"

RE_SUJETO = re.compile(r"\d{3}_S_\d{4}")
RE_FECHA = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


# ----------------------------------------------------------------------------
# Búsqueda de series
# ----------------------------------------------------------------------------
def es_dicom(nombre: str) -> bool:
    """ADNI usa .dcm, pero algunos volcados antiguos no llevan extensión."""
    return not nombre.startswith(".") and (nombre.lower().endswith(".dcm") or "." not in nombre)


def encontrar_series(origen: Path, patron_t1: re.Pattern, min_archivos: int):
    """
    Recorre el árbol y devuelve (series_t1, n_omitidas), donde cada serie es un dict con
    sujeto, fecha, descripción, carpeta y número de archivos.
    """
    series, omitidas = [], 0

    for raiz, _, archivos in os.walk(origen):
        dicoms = [a for a in archivos if es_dicom(a)]
        if len(dicoms) < min_archivos:
            continue

        carpeta = Path(raiz)
        partes = carpeta.relative_to(origen).parts
        if not partes:
            continue  # DICOMs sueltos en la raíz: no sabemos de qué sujeto son

        ruta_rel = "/".join(partes)
        if not patron_t1.search(ruta_rel.lower()):
            omitidas += 1
            print(f"  [omitida, no parece T1] {ruta_rel}")
            continue

        sujeto = next((p for p in partes if RE_SUJETO.fullmatch(p)), partes[0])
        fecha = None
        for p in partes:
            m = RE_FECHA.search(p)
            if m:
                fecha = "".join(m.groups())  # AAAAMMDD
                break

        series.append({
            "sujeto": sujeto,
            "fecha": fecha,
            "descripcion": partes[1] if len(partes) > 1 else "",
            "carpeta": carpeta,
            "n_archivos": len(dicoms),
        })

    series.sort(key=lambda s: (s["sujeto"], s["fecha"] or "", str(s["carpeta"])))
    return series, omitidas


def asignar_nombres(series):
    """
    Nombre BIDS-compatible: sub-<id sin guiones bajos>_ses-<AAAAMMDD>[_run-NN]_T1w.
    Se añade run solo si hay más de una serie en la misma sesión.
    """
    grupos = defaultdict(list)
    for s in series:
        sid = re.sub(r"[^A-Za-z0-9]", "", s["sujeto"])
        ses = s["fecha"] or "sinfecha"
        s["sid"], s["ses"] = sid, ses
        grupos[(sid, ses)].append(s)

    for (sid, ses), grupo in grupos.items():
        for i, s in enumerate(grupo, start=1):
            run = f"_run-{i:02d}" if len(grupo) > 1 else ""
            s["nombre"] = f"sub-{sid}_ses-{ses}{run}_T1w.nii.gz"
    return series


# ----------------------------------------------------------------------------
# Conversión
# ----------------------------------------------------------------------------
def convertir_con_dcm2niix(exe: str, carpeta_dicom: Path, tmp: Path):
    """-i y: ignora localizadores / derivadas / 2D. -b y: escribe el .json BIDS."""
    cmd = [exe, "-z", "y", "-b", "y", "-i", "y", "-f", "serie", "-o", str(tmp), str(carpeta_dicom)]
    resultado = subprocess.run(cmd, capture_output=True, text=True)
    if resultado.returncode != 0:
        # Código != 0 no siempre es fatal (p. ej. "convertidos algunos pero no todos");
        # lo decide el llamador según si aparecieron NIfTI.
        print(f"     [dcm2niix código {resultado.returncode}] {resultado.stdout.strip()[-300:]}")


def convertir_con_dicom2nifti(carpeta_dicom: Path, tmp: Path):
    """Alternativa. No corrige inclinación de gantry ni genera .json."""
    import dicom2nifti
    import dicom2nifti.settings as ajustes
    ajustes.disable_validate_orthogonal()  # silencia el aviso: revisa la cabecera después
    dicom2nifti.convert_directory(str(carpeta_dicom), str(tmp), compression=True, reorient=True)


def elegir_nifti(tmp: Path):
    """Devuelve (elegido, descartados). Si salen varios, el volumen más grande."""
    candidatos = sorted(tmp.glob("*.nii.gz"), key=lambda p: p.stat().st_size, reverse=True)
    if not candidatos:
        return None, []
    return candidatos[0], candidatos[1:]


def completar_sidecar(ruta_json: Path, serie: dict):
    """Garantiza SeriesDescription y AcquisitionDate, que usa es_secuencia_t1 / obtener_fecha_adquisicion."""
    datos = {}
    if ruta_json.exists():
        try:
            datos = json.loads(ruta_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            datos = {}

    datos.setdefault("SeriesDescription", serie["descripcion"])
    if serie["fecha"]:
        f = serie["fecha"]
        datos.setdefault("AcquisitionDate", f"{f[:4]}-{f[4:6]}-{f[6:]}")
    datos["MedVisionConversion"] = {
        "carpeta_dicom": str(serie["carpeta"]),
        "fecha_conversion": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    ruta_json.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")


def comprobar_cabecera(ruta_nifti: Path):
    """Devuelve (info, avisos). Detecta ejes no ortogonales (inclinación/cizallamiento)."""
    try:
        import nibabel as nib
        import numpy as np
    except ImportError:
        return {}, ["nibabel no instalado: no se comprobó la cabecera"]

    try:
        img = nib.load(str(ruta_nifti))
        A = img.affine[:3, :3]
        cols = A / np.linalg.norm(A, axis=0)
        desviacion = float(np.abs(cols.T @ cols - np.eye(3)).max())
        info = {
            "shape": "x".join(str(n) for n in img.shape),
            "zooms": "x".join(f"{z:.2f}" for z in img.header.get_zooms()[:3]),
            "orientacion": "".join(nib.aff2axcodes(img.affine)),
            "desviacion_ortogonal": round(desviacion, 4),
        }
        avisos = []
        if len(img.shape) != 3:
            avisos.append(f"la imagen no es 3D (shape {info['shape']})")
        if desviacion > 0.01:
            avisos.append(f"ejes no ortogonales (desviación {desviacion:.3f}): posible inclinación o cizallamiento")
        return info, avisos
    except Exception as e:  # nibabel puede fallar con archivos corruptos
        return {}, [f"no se pudo leer la cabecera: {e}"]


# ----------------------------------------------------------------------------
# Programa principal
# ----------------------------------------------------------------------------
def sujetos_con_varias_sesiones(destino: Path):
    patron = re.compile(r"sub-(?P<sub>[A-Za-z0-9]+)_ses-(?P<ses>[A-Za-z0-9]+)(?:_run-\d+)?_T1w\.nii\.gz$")
    por_sujeto = defaultdict(set)
    for f in destino.glob("*.nii.gz"):
        m = patron.match(f.name)
        if m:
            por_sujeto[m["sub"]].add(m["ses"])
    return {s: sorted(ses) for s, ses in por_sujeto.items() if len(ses) >= 2}


def main():
    ap = argparse.ArgumentParser(description="Conversión masiva ADNI DICOM -> NIfTI (MedVision)")
    ap.add_argument("-i", "--origen", default=ORIGEN_POR_DEFECTO, help="carpeta ADNI con una subcarpeta por sujeto")
    ap.add_argument("-o", "--destino", default=DESTINO_POR_DEFECTO, help="carpeta de salida de los .nii.gz")
    ap.add_argument("--motor", choices=["dcm2niix", "dicom2nifti"], default="dcm2niix")
    ap.add_argument("--dcm2niix", default="dcm2niix", help="ruta al ejecutable de dcm2niix si no está en el PATH")
    ap.add_argument("--patron", default=PATRON_T1_POR_DEFECTO, help="regex para reconocer series T1 en la ruta")
    ap.add_argument("--min-archivos", type=int, default=20, help="mínimo de DICOMs para considerar que es un volumen")
    ap.add_argument("--forzar", action="store_true", help="reconvertir aunque el .nii.gz ya exista")
    ap.add_argument("--dry-run", action="store_true", help="solo listar lo que se convertiría")
    args = ap.parse_args()

    origen, destino = Path(args.origen), Path(args.destino)
    if not origen.is_dir():
        print(f"[ERROR] No existe la carpeta de origen: {origen}")
        return 1

    exe = None
    if args.motor == "dcm2niix" and not args.dry_run:
        exe = shutil.which(args.dcm2niix)
        if exe is None:
            print("[ERROR] No se encontró dcm2niix.")
            print("  Descárgalo de https://github.com/rordenlab/dcm2niix (releases), añádelo al PATH")
            print("  o pásalo con --dcm2niix <ruta>. Si no puedes, usa --motor dicom2nifti.")
            return 1

    try:
        patron = re.compile(args.patron.lower())
    except re.error as e:
        print(f"[ERROR] --patron no es una expresión regular válida: {e}")
        return 1

    print(f"Buscando series T1 en: {origen}")
    series, omitidas = encontrar_series(origen, patron, args.min_archivos)
    series = asignar_nombres(series)
    print(f"\n{len(series)} serie(s) T1 encontradas, {omitidas} omitida(s).\n")

    if args.dry_run:
        for s in series:
            aviso = "" if s["fecha"] else "   [¡sin fecha en la ruta!]"
            print(f"  {s['nombre']}  <-  {s['carpeta']} ({s['n_archivos']} archivos){aviso}")
        return 0

    destino.mkdir(parents=True, exist_ok=True)
    ruta_manifest = destino / "conversion_manifest.csv"
    manifest_nuevo = not ruta_manifest.exists()
    campos = ["sujeto", "sesion", "serie", "archivo", "n_dicom", "shape", "zooms",
              "orientacion", "desviacion_ortogonal", "avisos", "carpeta_dicom"]

    convertidas = saltadas = errores = 0
    with open(ruta_manifest, "a", newline="", encoding="utf-8") as fm:
        escritor = csv.DictWriter(fm, fieldnames=campos)
        if manifest_nuevo:
            escritor.writeheader()

        for s in series:
            salida = destino / s["nombre"]
            print(f"{s['sujeto']} {s['fecha'] or 'sin fecha'} -> {s['nombre']}")

            if salida.exists() and not args.forzar:
                print("   ya existe, se omite (usa --forzar para rehacerlo)")
                saltadas += 1
                continue
            if not s["fecha"]:
                print("   [AVISO] sin fecha en la ruta: el orden temporal de las sesiones no se podrá garantizar")

            with tempfile.TemporaryDirectory(prefix="adni_") as t:
                tmp = Path(t)
                try:
                    if args.motor == "dcm2niix":
                        convertir_con_dcm2niix(exe, s["carpeta"], tmp)
                    else:
                        convertir_con_dicom2nifti(s["carpeta"], tmp)
                except Exception as e:
                    print(f"   [ERROR] Falló la conversión: {e}")
                    errores += 1
                    continue

                elegido, descartados = elegir_nifti(tmp)
                if elegido is None:
                    print("   [ERROR] No se generó ningún .nii.gz")
                    errores += 1
                    continue
                if descartados:
                    print(f"   [AVISO] Salieron {len(descartados) + 1} volúmenes; se usa el más grande "
                          f"({elegido.name}). Descartados: {[d.name for d in descartados]}")

                json_tmp = Path(str(elegido)[:-len(".nii.gz")] + ".json")
                shutil.move(str(elegido), str(salida))
                json_final = Path(str(salida)[:-len(".nii.gz")] + ".json")
                if json_tmp.exists():
                    shutil.move(str(json_tmp), str(json_final))
                completar_sidecar(json_final, s)

            info, avisos = comprobar_cabecera(salida)
            for a in avisos:
                print(f"   [AVISO] {a}")
            if info:
                print(f"   OK  shape={info['shape']}  vóxel={info['zooms']} mm  orientación={info['orientacion']}")
            else:
                print("   OK")

            escritor.writerow({
                "sujeto": s["sujeto"], "sesion": s["ses"], "serie": s["descripcion"],
                "archivo": s["nombre"], "n_dicom": s["n_archivos"],
                "shape": info.get("shape", ""), "zooms": info.get("zooms", ""),
                "orientacion": info.get("orientacion", ""),
                "desviacion_ortogonal": info.get("desviacion_ortogonal", ""),
                "avisos": " | ".join(avisos), "carpeta_dicom": str(s["carpeta"]),
            })
            convertidas += 1

    print(f"\nResumen: {convertidas} convertida(s), {saltadas} ya existente(s), {errores} con error.")
    print(f"Manifiesto: {ruta_manifest}")

    pares = sujetos_con_varias_sesiones(destino)
    if pares:
        print("\nSujetos con 2 o más sesiones (candidatos a SIENA):")
        for sub, sesiones in pares.items():
            print(f"  sub-{sub}: {', '.join('ses-' + x for x in sesiones)}")

    return 0 if errores == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
import os
from pathlib import Path
import dicom2nifti
import dicom2nifti.settings as settings

# Desactivamos comprobaciones estrictas para evitar que rechace los DICOMs antiguos de ADNI
settings.disable_validate_orthogonal()

def convertir_lote_adni(carpeta_origen, carpeta_destino):
    os.makedirs(carpeta_destino, exist_ok=True)
    print(f"Buscando carpetas en: {carpeta_origen}")
    
    # Recorremos cada carpeta de sujeto directamente (ej: 011_S_0002)
    sujetos = [d for d in os.listdir(carpeta_origen) if os.path.isdir(os.path.join(carpeta_origen, d))]
    
    for sujeto in sujetos:
        ruta_sujeto = os.path.join(carpeta_origen, sujeto)
        print(f"\nProcesando sujeto: {sujeto}")
        
        # Buscamos recursivamente dentro del sujeto la carpeta que contenga archivos .dcm
        carpeta_dicom_encontrada = None
        for root, dirs, files in os.walk(ruta_sujeto):
            if any(f.lower().endswith('.dcm') or '.' not in f for f in files):
                # Comprobamos que tenga una cantidad razonable de archivos (es un volumen)
                archivos_validos = [f for f in files if not f.startswith('.')]
                if len(archivos_validos) > 10:  # Un mprage tiene cientos de rodajas
                    carpeta_dicom_encontrada = root
                    break
        
        if carpeta_dicom_encontrada:
            try:
                print(f" -> Encontrados DICOMs en: {carpeta_dicom_encontrada}")
                # Convertimos usando una carpeta temporal de salida de la librería
                temp_out = os.path.join(carpeta_destino, "temp")
                os.makedirs(temp_out, exist_ok=True)
                
                dicom2nifti.convert_directory(carpeta_dicom_encontrada, temp_out, compression=True, reorient=True)
                
                # Buscamos el archivo .nii.gz generado y lo libramos con el nombre correcto del sujeto
                generados = [f for f in os.listdir(temp_out) if f.endswith('.nii.gz')]
                if generados:
                    archivo_original = os.path.join(temp_out, generados[0])
                    nombre_final = f"sub-{sujeto}_T1w.nii.gz"
                    ruta_final = os.path.join(carpeta_destino, nombre_final)
                    
                    if os.path.exists(ruta_final):
                        os.remove(ruta_final)
                    os.rename(archivo_original, ruta_final)
                    print(f" -> ¡Éxito! Creado: {nombre_final}")
                
                # Limpiamos el temporal
                for f in os.listdir(temp_out):
                    os.remove(os.path.join(temp_out, f))
                os.rmdir(temp_out)
                
            except Exception as e:
                print(f" -> [ERROR] Falló la conversión para {sujeto}: {e}")
        else:
            print(f" -> [AVISO] No se encontró una serie DICOM válida para {sujeto}")

if __name__ == "__main__":
    ORIGEN = r"C:\Users\Miriam\Downloads\cerebro malo\ADNI"
    DESTINO = r"C:\Users\Miriam\Downloads\cerebro malo\salida"
    
    convertir_lote_adni(ORIGEN, DESTINO)
    print("\n¡Proceso de conversión masiva finalizado!")
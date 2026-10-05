import configparser

def cargar_configuracion(ruta_config: str) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    archivos_leidos = config.read(ruta_config, encoding='utf-8')
    if not archivos_leidos:
        raise FileNotFoundError(f"No se encontró el archivo de configuración: {ruta_config}")
    if 'Rutas' not in config:
        raise KeyError(f"El archivo {ruta_config} no tiene la sección [Rutas].")
    return config
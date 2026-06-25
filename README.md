# Research_Blender_MedVisor

Medical image visualization with Blender. Automatiza el flujo de trabajo de segmentación médica permitiendo importar volúmenes de Resonancia Magnética (MRI) en formato NIfTI (`.nii.gz`), ejecutar la red neuronal HD-BET en segundo plano y generar automáticamente una malla 3D optimizada en el *viewport* de Blender.

## Prerrequisitos del Sistema

Dado que el procesamiento pesado recae sobre modelos de Inteligencia Artificial, **MedVision requiere tener instalado HD-BET en tu sistema operativo** antes de usar el addon.

### Instalación de dependencias externas:
Debido a la complejidad de las librerías de IA, se recomienda encarecidamente realizar la instalación dentro de un **entorno virtual de Python** dedicado para garantizar la estabilidad y evitar conflictos de dependencias con Blender:

1. Instala la herramienta ejecutando: `pip install hd-bet` o desde el repositorio oficial.
3. Anota la ruta completa donde se encuentra el ejecutable `hd-bet` (ej. `/path/Scripts/hd-bet.exe`).

> **Nota:** HD-BET requiere un entorno Python funcional. Si dispones de una GPU compatible, el procesamiento tomará menos de 5 segundos. En caso de usar CPU, el proceso puede tardar unos minutos. Para más detalles sobre la IA, consulta el [repositorio oficial de HD-BET](https://github.com/MIC-DKFZ/hd-bet).

## Instalación del Addon en Blender

1. Descarga el código de este repositorio como un archivo `.zip`.
2. Abre Blender (versión 3.6 o superior).
3. Dirígete a **Edit > Preferences > Add-ons**.
4. Haz clic en **Install...** y selecciona el archivo `.zip`.
5. Activa la casilla `3D View: MedVision` para habilitarlo.

## Uso del Addon

Una vez activado, el addon configurará el entorno automáticamente:

1. El sistema creará un espacio de trabajo (*Workspace*) dedicado llamado **MedVision**, configurado automáticamente con vista cuádruple (*QuadView*) para análisis clínico simultáneo.
2. En el panel lateral derecho del *Viewport* (tecla `N`), busca la pestaña **MedVision Control**.
3. **Archivo MRI:** Utiliza el selector para elegir tu volumen en formato `.nii.gz`.
4. **Ruta HD-BET:** Indica la ruta completa al ejecutable de `hd-bet` que instalaste en tu entorno virtual.
5. **Extraer Cerebro:** Haz clic en este botón. Blender ejecutará el proceso en segundo plano, segmentará el parénquima cerebral y renderizará la malla tridimensional centrada y orientada automáticamente en el centro de la escena.

## Limitaciones y Alcance

* **Modalidad:** Pipeline validado exclusivamente para volúmenes de **Resonancia Magnética (MRI)**.
* **Formatos incompatibles:** El uso de datos basados en densidad radiológica, como la Angiotomografía (CTA) o PET, no es compatible con el modelo de segmentación actual.

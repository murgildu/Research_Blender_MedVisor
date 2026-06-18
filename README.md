# Research_Blender_MedVisor
Medical image visualization with Blender. Que automatiza el flujo de trabajo de segmentación médica. Permite importar volúmenes de Resonancia Magnética (MRI) en formato NIfTI (`.nii.gz`), ejecutar una red neuronal de extracción cerebral en segundo plano y generar automáticamente una malla 3D optimizada directamente en el *viewport* de Blender.

## Prerrequisitos del Sistema

Dado que el procesamiento pesado recae sobre modelos de Inteligencia Artificial, **MedVision requiere que la herramienta HD-BET esté instalada previamente en tu sistema operativo** antes de activar el addon en Blender.

### Instalación de dependencias externas:
Abre la terminal de tu sistema operativo (Símbolo del sistema en Windows o Terminal en Linux/macOS) y ejecuta el siguiente comando para instalar la herramienta de IA:

pip install hd-bet

> **Nota:** HD-BET requiere un entorno Python funcional. Si dispones de una GPU compatible, el procesamiento tomará menos de 5 segundos. En caso de usar CPU, el proceso puede tardar unos minutos. Para más detalles sobre la IA, consulta el [repositorio oficial de HD-BET](https://github.com/MIC-DKFZ/hd-bet).

## Instalación del Addon en Blender

1. Descarga el código de este repositorio como un archivo `.zip`.
2. Abre Blender (versión 3.6 o superior).
3. Dirígete a **Edit > Preferences > Add-ons**.
4. Haz clic en el botón **Install...** situado en la parte superior derecha.
5. Selecciona el archivo `.zip` descargado y haz clic en **Install Add-on**.
6. Activa la casilla junto a `3D View: MedVision` para habilitarlo.

## Uso del Addon

Una vez activado, MedVision preparará automáticamente el entorno de trabajo:

1. El addon creará un espacio de trabajo (*Workspace*) llamado **MedVision**.
2. En el panel lateral derecho del *Viewport* (tecla `N`), busca la pestaña **MedVision_Solid**.
3. **Directorio MRI:** Utiliza el selector de archivos para elegir tu volumen de resonancia magnética en formato `.nii.gz` (Secuencias T1-weighted recomendadas).
4. **Configurar Entorno:** Haz clic en este botón para activar la vista médica (*QuadView*) y el HUD de orientación ortogonal.
5. **Extraer Cerebro:** Ejecuta la herramienta. Blender llamará a HD-BET en segundo plano, aislará el parénquima cerebral y aplicará el algoritmo de *marching cubes* para renderizar la malla tridimensional en el centro de la escena.

## Limitaciones y Alcance

* **Modalidad:** Este pipeline de momento esta siendo validado exclusivamente para volúmenes de **Resonancia Magnética (MRI)**.
* **Formatos incompatibles:** El uso de datos basados en densidad radiológica, como la Angiotomografía (CTA) o PET, producirá mallas defectuosas.

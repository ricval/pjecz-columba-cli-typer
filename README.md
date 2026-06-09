# pjecz-columba-cli-typer

Voceador de la recepción.

## Requerimientos

- Python 3.14 o superior
- Piper Utils
- Pulseaudio Utils

## Instalación

Instalar Piper Utils (para Fedora Linux)

```bash
sudo dnf install pipewire-utils
```

Instalar Pulseaudio Utils (para Fedora Linux)

```bash
sudo dnf install pulseaudio-utils
```

Crerar entorno virtual

```bash
python -m venv .venv
```

Activar entorno virtual

```bashbash
source .venv/bin/activate
```

Instalar dependencias con `uv`

```bash
uv install
```

Crear el directorio para los modelos de voz de Piper

```bash
mkdir -p ~/.local/share/piper-voices
```

Descargar los modelos de voz (archivos `.onnx` y `.onnx.json`) desde [HuggingFace](https://huggingface.co)

- [Español España](https://huggingface.co/rhasspy/piper-voices/tree/main/es/es_ES)
    - es_ES-carlfm-x_low
    - es_ES-davefx-medium
    - es_ES-sharvard-medium
- [Español México](https://huggingface.co/rhasspy/piper-voices/tree/main/es/es_MX)
    - es_MX-claude-high
    - es_MX-ald-medium

Moverlos al directorio de Piper

```bash
mv es_*.onnx ~/.local/share/piper-voices/
mv es_*.onnx.json ~/.local/share/piper-voices/
```

## Configuración

Crear un archivo `.env` en la raíz del proyecto para cambiar los valores por defecto de las siguientes variables de entorno:

```env
REDIS_URL=redis://localhost:6379/0
SERVIR_HOST=0.0.0.0                     # FastAPI escuchará en todas las interfaces de red
SERVIR_PORT=8080                        # FastAPI escuchará en este puerto
VOZ=es_MX-claude-high                   # Voz a utilizar (debe coincidir con el nombre del archivo .onnx sin la extensión)
VOZ_VELOCIDAD=1.0                       # Velocidad de la voz (0.5 = mitad de velocidad, 2.0 = el doble de velocidad)
VOCEAR_COLA=vocear:pendientes           # Nombre de la cola en Redis
VOCEAR_ITEM_PREFIJO=vocear:item:        # Prefijo para los items en Redis
VOCEAR_REPETIR_PREFIJO=vocear:repetir:  # Prefijo para los items de repetición en Redis
VOCEAR_REPETIR_CADA=30                  # Segundos entre repeticiones
VOCEAR_TTL=120                          # Tiempo de vida de cada item en segundos
```

Crear un archivo `.bashrc` en la raíz del proyecto para cargar las variables de entorno al activar el entorno virtual:

```bash
# pjecz-columba-cli-typer

if [ -f ~/.bashrc ]
then
    . ~/.bashrc
fi

if command -v figlet &> /dev/null
then
    figlet Columba CLI Typer
else
    echo "== Columba CLI Typer"
fi
echo

if [ -f .env ]
then
    export $(grep -v '^#' .env | xargs)
    echo "-- Variables de entorno"
    echo "   REDIS_URL: ${REDIS_URL}"
    echo "   SERVIR_HOST: ${SERVIR_HOST}"
    echo "   SERVIR_PORT: ${SERVIR_PORT}"
    echo "   VOZ: ${VOZ}"
    echo "   VOZ_VELOCIDAD: ${VOZ_VELOCIDAD}"
    echo "   VOCEAR_COLA: ${VOCEAR_COLA}"
    echo "   VOCEAR_ITEM_PREFIJO: ${VOCEAR_ITEM_PREFIJO}"
    echo "   VOCEAR_REPETIR_PREFIJO: ${VOCEAR_REPETIR_PREFIJO}"
    echo "   VOCEAR_REPETIR_CADA: ${VOCEAR_REPETIR_CADA}"
    echo "   VOCEAR_TTL: ${VOCEAR_TTL}"
    echo
fi

if [ -d .venv ]
then
    echo "-- Python Virtual Environment"
    source .venv/bin/activate
    echo "   $(python3 --version)"
    export PYTHONPATH=$(pwd)
    echo "   PYTHONPATH: ${PYTHONPATH}"
    echo
    alias cli="uv run ${PWD}/pjecz_columba_cli_typer/app.py"
    echo "-- Ejecutar el CLI"
    echo "   cli --help"
    echo
fi
```

## Uso

Cargar las variables de entorno y activar el entorno virtual:

```bash
source .bashrc
```

Ejecutar el CLI:

```bash
cli --help
```

Listar las voces disponibles:

```bash
cli voces
```

Listar los `skins` de audio disponibles:

```bash
cli listar
```

Vocear un texto:

```bash
cli hablar 'Buenas noches'
```

Arrancar el servidor FastAPI para recibir las peticiones de vocear:

```bash
cli servir
```

Enviar una petición a la API para vocear un texto (ID entero y el mensaje a vocear):

```bash
cli enviar 12 'Buenas noches'
```

"""
PJECZ Columba CLI Typer App
"""

import asyncio
import json
import os
import subprocess
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from pydantic_settings import BaseSettings
from redis import asyncio as aioredis
from rich.console import Console
from rich.table import Table
from typer import Argument, Exit, Option, Typer

load_dotenv()

app = Typer(help="Vocero de la recepción.")

# Voces disponibles en Piper para español
VOCES = {
    "es_MX-claude-high": {
        "onnx": "es_MX-claude-high.onnx",
        "json": "es_MX-claude-high.onnx.json",
    },
    "es_MX-ald-medium": {
        "onnx": "es_MX-ald-medium.onnx",
        "json": "es_MX-ald-medium.onnx.json",
    },
    "es_ES-carlfm-x_low": {
        "onnx": "es_ES-carlfm-x_low.onnx",
        "json": "es_ES-carlfm-x_low.onnx.json",
    },
    "es_ES-davefx-medium": {
        "onnx": "es_ES-davefx-medium.onnx",
        "json": "es_ES-davefx-medium.onnx.json",
    },
    "es_ES-sharvard-medium": {
        "onnx": "es_ES-sharvard-medium.onnx",
        "json": "es_ES-sharvard-medium.onnx.json",
    },
}
MODELOS_DIR = Path.home() / ".local" / "share" / "piper-voices"


# -------------
# Configuración
# -------------


class Settings(BaseSettings):
    """Settings"""

    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    SERVIR_HOST: str = os.getenv("SERVIR_HOST", "0.0.0.0")
    SERVIR_PORT: int = int(os.getenv("SERVIR_PORT", "8080"))
    VOZ: str = os.getenv("VOZ", "es_MX-claude-high")
    VOZ_VELOCIDAD: float = float(os.getenv("VOZ_VELOCIDAD", "1.0"))
    VOCEAR_COLA: str = os.getenv("VOCEAR_COLA", "vocear:pendientes")
    VOCEAR_ITEM_PREFIJO: str = os.getenv("VOCEAR_ITEM_PREFIJO", "vocear:item:")
    VOCEAR_REPETIR_PREFIJO: str = os.getenv("VOCEAR_REPETIR_PREFIJO", "vocear:repetir:")
    VOCEAR_REPETIR_CADA: int = int(os.getenv("VOCEAR_REPETIR_CADA", "30"))  # Cantidad de segundos entre repeticiones
    VOCEAR_TTL: int = int(os.getenv("VOCEAR_TTL", "120"))  # Cantidad de segundos que permanece una Atención en Redis


configuracion = Settings()

# ---------
# Funciones
# ---------


def _listar_sinks() -> list[dict]:
    """Lista los sinks de audio disponibles."""
    console = Console()
    try:
        out = subprocess.check_output(["pactl", "list", "short", "sinks"], text=True)
    except FileNotFoundError:
        console.print("[red]ERROR: pactl no encontrado.[/red] Instálalo con: sudo dnf install pulseaudio-utils")
        raise Exit(1)
    sinks = []
    for line in out.strip().splitlines():
        partes = line.split("\t")
        if len(partes) >= 2:
            sinks.append(
                {
                    "id": partes[0].strip(),
                    "nombre": partes[1].strip(),
                    "estado": partes[4].strip() if len(partes) > 4 else "",
                }
            )
    return sinks


def _elegir_voz(nombre_voz: str) -> tuple[Path, Path]:
    """Devuelve las rutas al modelo ONNX y su JSON para la voz elegida."""
    console = Console()
    if nombre_voz not in VOCES:
        console.print(f"[yellow]Voz '{nombre_voz}' no encontrada.[/yellow] Usa 'voces' para ver opciones.")
        raise Exit(1)
    onnx_path = MODELOS_DIR / VOCES[nombre_voz]["onnx"]
    json_path = MODELOS_DIR / VOCES[nombre_voz]["json"]
    if not onnx_path.exists() or not json_path.exists():
        console.print(f"[yellow]Modelo '{nombre_voz}' no encontrado en {MODELOS_DIR}.[/yellow]")
        raise Exit(1)
    return onnx_path, json_path


def _reproducir(wav: Path, dispositivo: str | None) -> None:
    """Reproduce el archivo WAV usando pw-cat."""
    console = Console()
    cmd = ["pw-cat", "--playback"]
    if dispositivo:
        cmd += ["--target", dispositivo]
    cmd.append(str(wav))
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        console.print("[red]pw-cat no encontrado.[/red] Instálalo con: sudo dnf install pipewire-utils")
        raise Exit(1)
    finally:
        wav.unlink(missing_ok=True)


def _sintetizar_wav(texto: str, onnx: Path, velocidad: float) -> Path:
    """Sintetiza texto a WAV usando piper."""
    console = Console()
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    wav_path = Path(tmp.name)
    try:
        proc = subprocess.run(
            [
                "piper",
                "--model",
                str(onnx),
                "--length-scale",
                str(round(1.0 / velocidad, 3)),  # >1 = más lento
                "--output_file",
                str(wav_path),
            ],
            input=texto,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            console.print(f"[red]ERROR en piper:[/red] {proc.stderr}")
            raise Exit(1)
    except FileNotFoundError:
        console.print("[red]piper no encontrado.[/red] Instálalo con: pip install piper-tts")
        raise Exit(1)
    return wav_path


# -----------
# App FastAPI
# -----------


class Atencion(BaseModel):
    """Esquema para recibir una atención."""

    id: int
    mensaje: str
    tiempo: str  # ISO 8601
    ttl_segundos: int = configuracion.VOCEAR_TTL


class AtencionQuitar(BaseModel):
    """Esquema para quitar una atención."""

    id: int


def vocear_texto(texto: str) -> None:
    """Función bloqueante para sintetizar y reproducir texto."""
    onnx, _ = _elegir_voz(configuracion.VOZ)
    wav = _sintetizar_wav(texto, onnx, configuracion.VOZ_VELOCIDAD)
    _reproducir(wav, dispositivo=None)  # Sink por defecto


async def worker_voz(redis: aioredis.Redis, stop_event: asyncio.Event):
    """Worker que escucha la cola de voz en Redis y reproduce los mensajes."""
    console = Console()
    console.print("[green]Worker de voz iniciado.[/green]")
    while not stop_event.is_set():
        # BRPOP bloquea hasta 1s; permite revisar stop periódicamente.
        res = await redis.brpop([configuracion.VOCEAR_COLA], timeout=1)
        if res is None:
            continue
        _, item_key = res
        crudo = await redis.get(item_key)
        if crudo is None:
            continue  # Expiró por TTL antes de vocearse: se descarta.
        datos = json.loads(crudo)
        await redis.delete(item_key)
        # Piper/pw-cat son bloqueantes: a un hilo para no congelar el loop.
        try:
            await asyncio.to_thread(vocear_texto, datos["mensaje"])
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Error al vocear texto:[/red] {exc}")
    console.print("[yellow]Worker de voz detenido.[/yellow]")


async def worker_repetir(redis: aioredis.Redis, stop_event: asyncio.Event):
    """Worker que encola periódicamente las Atenciones repetibles hasta que expiren su TTL."""
    console = Console()
    console.print("[green]Worker de repetición iniciado.[/green]")
    while not stop_event.is_set():
        async for repeat_key in redis.scan_iter(f"{configuracion.VOCEAR_REPETIR_PREFIJO}*"):
            crudo = await redis.get(repeat_key)
            if crudo is None:
                continue  # Expiró por TTL: ya no se repite.
            item_key = f"{configuracion.VOCEAR_ITEM_PREFIJO}{uuid.uuid4().hex}"
            # TTL corto: solo necesita sobrevivir hasta que el worker_voz lo consuma.
            await redis.set(item_key, crudo, ex=configuracion.VOCEAR_REPETIR_CADA)
            await redis.lpush(configuracion.VOCEAR_COLA, item_key)
        # Espera el intervalo o sale inmediatamente si se pide detener.
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=configuracion.VOCEAR_REPETIR_CADA)
        except asyncio.TimeoutError:
            pass
    console.print("[yellow]Worker de repetición detenido.[/yellow]")


def crear_app_fastapi() -> FastAPI:
    """Crea la app FastAPI para el servidor de voz."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Inicializa recursos al iniciar y los limpia al cerrar."""
        app.state.redis = aioredis.from_url(configuracion.REDIS_URL, decode_responses=True)
        app.state.stop = asyncio.Event()
        app.state.worker = asyncio.create_task(worker_voz(app.state.redis, app.state.stop))
        app.state.worker_repetir = asyncio.create_task(worker_repetir(app.state.redis, app.state.stop))
        try:
            yield
        finally:
            app.state.stop.set()
            await app.state.worker
            await app.state.worker_repetir
            await app.state.redis.aclose()

    fastapi_app = FastAPI(
        title="Columba API",
        description="API para el vocero de la recepción.",
        lifespan=lifespan,
    )

    @fastapi_app.post("/hablar")
    async def hablar_api(atencion: Atencion):
        """Endpoint para recibir atenciones para hablar."""
        redis: aioredis.Redis = fastapi_app.state.redis
        item_key = f"{configuracion.VOCEAR_ITEM_PREFIJO}{uuid.uuid4().hex}"
        payload = json.dumps(
            {
                "id": atencion.id,
                "mensaje": atencion.mensaje,
                "tiempo": atencion.tiempo,
                "ttl_segundos": atencion.ttl_segundos,
            }
        )
        await redis.set(item_key, payload, ex=configuracion.VOCEAR_TTL)
        await redis.lpush(configuracion.VOCEAR_COLA, item_key)
        return {"success": True, "message": f"Item: {item_key}"}

    @fastapi_app.post("/agregar")
    async def agregar_api(atencion: Atencion):
        """Endpoint para agregar una atencion que se va repetir. Si el ID ya existe, se omite."""
        redis: aioredis.Redis = fastapi_app.state.redis
        repeat_key = f"{configuracion.VOCEAR_REPETIR_PREFIJO}{atencion.id}"
        if await redis.exists(repeat_key):
            return {"success": False, "message": f"ID {atencion.id} ya existe, se omite."}
        payload = json.dumps(
            {
                "id": atencion.id,
                "mensaje": atencion.mensaje,
                "tiempo": atencion.tiempo,
                "ttl_segundos": atencion.ttl_segundos,
            }
        )
        await redis.set(repeat_key, payload, ex=atencion.ttl_segundos)
        # Hablar de inmediato sin esperar el primer ciclo de repetición
        item_key = f"{configuracion.VOCEAR_ITEM_PREFIJO}{uuid.uuid4().hex}"
        await redis.set(item_key, payload, ex=configuracion.VOCEAR_REPETIR_CADA)
        await redis.lpush(configuracion.VOCEAR_COLA, item_key)
        return {"success": True, "message": f"Atención {atencion.id} agregada para repetición."}

    @fastapi_app.post("/quitar")
    async def quitar_api(atencion_quitar: AtencionQuitar):
        """Endpoint para quitar una atencion, para que se deje de repetir."""
        redis: aioredis.Redis = fastapi_app.state.redis
        repeat_key = f"{configuracion.VOCEAR_REPETIR_PREFIJO}{atencion_quitar.id}"
        deleted = await redis.delete(repeat_key)
        if deleted:
            return {"success": True, "message": f"Atención {atencion_quitar.id} eliminada."}
        # Si no se encuentra, no se hace nada, simplemente entrega el success en True y el mensaje de que no se encontró
        return {"success": True, "message": f"ID {atencion_quitar.id} no encontrado."}

    return fastapi_app


# --------
# Comandos
# --------


@app.command()
def voces():
    """Lista las voces en español disponibles para Piper."""
    console = Console()
    table = Table(title="Voces Piper en Español")
    table.add_column("Estado", justify="center")
    table.add_column("Nombre de Voz", justify="left")
    for nombre in VOCES:
        descargada = (MODELOS_DIR / f"{nombre}.onnx").exists()
        estado = "✔ descargada" if descargada else "  no descargada"
        table.add_row(estado, nombre)
    console.print(table)


@app.command()
def listar():
    """Lista los dispositivos de audio disponibles (sinks)."""
    console = Console()
    sinks = _listar_sinks()
    if not sinks:
        console.print("[yellow]No se encontraron sinks de audio.[/yellow]")
        raise Exit(1)
    table = Table(title="Sinks de Audio Disponibles")
    table.add_column("ID", justify="center")
    table.add_column("Nombre", justify="left")
    table.add_column("Estado", justify="center")
    for s in sinks:
        table.add_row(s["id"], s["nombre"], s["estado"])
    console.print(table)


@app.command()
def hablar(
    texto: str,
    dispositivo: str = Option(
        None,
        "--dispositivo",
        "-d",
        help="Nombre del sink (usa 'listar'). Sin valor usa el sink por defecto.",
    ),
    voz: str = Option(
        configuracion.VOZ,
        "--voz",
        "-z",
        help="Voz Piper a usar (usa 'voces' para ver opciones).",
    ),
    velocidad: float = Option(
        1.0,
        "--velocidad",
        "-v",
        help="Velocidad del habla. 1.0 = normal, 1.2 = más rápido, 0.8 = más lento.",
    ),
):
    """Hablar el texto especificado usando Piper TTS."""
    console = Console()
    console.print(f"[blue]Hablando:[/blue] {texto}")
    onnx, _ = _elegir_voz(voz)
    wav = _sintetizar_wav(texto, onnx, velocidad)
    _reproducir(wav, dispositivo)


@app.command()
def servir(
    host: str = Option(configuracion.SERVIR_HOST, help="Interfaz de red a escuchar."),
    puerto: int = Option(configuracion.SERVIR_PORT, help="Puerto a escuchar."),
):
    """Inicia el servidor FastAPI para recibir atenciones."""
    console = Console()
    console.print("[green]Iniciando servidor FastAPI...[/green]")
    uvicorn.run(crear_app_fastapi(), host=host, port=puerto, log_level="info")


@app.command()
def enviar(
    id: int = Argument(..., help="ID de la atención."),
    mensaje: str = Argument(..., help="Mensaje a hablar."),
    tiempo: str = Option(datetime.now().isoformat(), help="Tiempo de la atención (ISO 8601)."),
    ttl: int = Option(configuracion.VOCEAR_TTL, help="TTL en segundos para el mensaje."),
):
    """Envía una atención al servidor de voz."""
    console = Console()
    payload = {
        "id": id,
        "mensaje": mensaje,
        "tiempo": tiempo,
        "ttl_segundos": ttl,
    }
    response = requests.post(f"http://{configuracion.SERVIR_HOST}:{configuracion.SERVIR_PORT}/hablar", json=payload)
    if response.status_code == 200:
        console.print("[green]Atención enviada exitosamente.[/green]")
    else:
        console.print(f"[red]Error al enviar atención:[/red] {response.text}")


if __name__ == "__main__":
    app()

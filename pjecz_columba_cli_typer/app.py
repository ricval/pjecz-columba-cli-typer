"""
PJECZ Columba CLI Typer App
"""

import subprocess
import tempfile
from pathlib import Path

from rich.console import Console
from rich.table import Table
from typer import Exit, Option, Typer

app = Typer(help="Vocero de la recepción.")

# Voces disponibles en Piper para español
# Fuente: https://huggingface.co/rhasspy/piper-voices
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
    onnx_path = Path(MODELOS_DIR, VOCES[nombre_voz]["onnx"])
    json_path = Path(MODELOS_DIR, VOCES[nombre_voz]["json"])
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
    """Lista los dispositivos de audio disponibles (sinks via pactl)."""
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
        "es_MX-claude-high",
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


if __name__ == "__main__":
    app()

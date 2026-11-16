"""Voice-only starter bot: ElevenLabs STT -> Gemini -> ElevenLabs TTS."""

import os
import sys
from pathlib import Path

# Keep package imports working when launched from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.elevenlabs.stt import CommitStrategy, ElevenLabsRealtimeSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.workers.runner import WorkerRunner

try:  # Direct script execution does not set a package context.
    from .tool_handlers import ConfirmationState, create_clinic_tool_schemas
    from . import dashboard_api as _dashboard_api
except ImportError:  # pragma: no cover - package-style runner
    from backend.tool_handlers import ConfirmationState, create_clinic_tool_schemas
    from backend import dashboard_api as _dashboard_api


# Always load the project-root .env, even if this script is run from backend/.
load_dotenv(PROJECT_ROOT / ".env")

SYSTEM_INSTRUCTION = (
    "You are the friendly receptionist for a clinic's phone line. Speak in short, "
    "natural sentences, one or two per turn. Never use lists, markdown, or emojis. "
    "Greet the caller briefly, then ask how you can help. Your only tasks are checking "
    "doctor availability, booking an appointment, and cancelling an appointment; "
    "politely decline other requests. Identify a caller only by the 10-digit phone "
    "number they say aloud. Never ask for a name, OTP, or other ID. "
    "For booking, ask which doctor or speciality and preferred day, then call "
    "check_doctor_availability. Offer only two or three returned choices, using the "
    "doctor name and spoken_slot. Never say doctor IDs or raw slot timestamps. Once "
    "the caller chooses, confirm the doctor and time, then ask for their phone number. "
    "For cancellation, ask for the phone number and use the cancellation tool. The "
    "server will read the number digit by digit and repeat the exact appointment and "
    "ask for one clear yes that confirms both the number and the requested change. "
    "Do not call a mutating tool again unless the caller has clearly said yes to that "
    "specific combined confirmation. A no, unclear answer, or changed request means "
    "nothing is changed. Never invent doctors, times, or confirmations; state only "
    "what tool results support. Follow the tool result's next_speech instruction. If "
    "a tool fails, explain briefly and offer checking another available option."
)

# Pipecat's development runner asks this function for transport settings when a
# browser connects. The browser client selects the local Small WebRTC transport.
TRANSPORT_PARAMS = {
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    ),
}


def required_env(name: str) -> str:
    """Return a required setting without ever logging its value."""
    value = os.getenv(name, "").strip()
    if not value or value.startswith("your-"):
        raise RuntimeError(
            f"Set {name} in the project-root .env file before starting a call."
        )
    return value


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments) -> None:
    """Build and run one voice conversation over the supplied transport."""
    api_key = required_env("ELEVENLABS_API_KEY")
    google_api_key = required_env("GOOGLE_API_KEY")
    voice_id = required_env("ELEVENLABS_VOICE_ID")

    stt = ElevenLabsRealtimeSTTService(
        api_key=api_key,
        # Pipecat's speech-stop signal sends one manual commit. Interim text is
        # not added to LLMContext; only the resulting committed transcript is.
        commit_strategy=CommitStrategy.MANUAL,
        include_timestamps=False,
        include_language_detection=False,
        settings=ElevenLabsRealtimeSTTService.Settings(
            model=os.getenv("ELEVENLABS_STT_MODEL", "scribe_v2_realtime")
        ),
    )

    llm = GoogleLLMService(
        api_key=google_api_key,
        settings=GoogleLLMService.Settings(
            model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
            system_instruction=SYSTEM_INSTRUCTION,
        ),
    )

    tts = ElevenLabsTTSService(
        api_key=api_key,
        settings=ElevenLabsTTSService.Settings(
            voice=voice_id,
            model=os.getenv("ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5"),
        ),
    )

    # Confirmation state is created per run_bot invocation, so callers never share it.
    confirmation_state = ConfirmationState()
    tool_schemas = create_clinic_tool_schemas(confirmation_state)
    # Pipecat 1.16 registers FunctionSchema handlers advertised by LLMContext.
    context = LLMContext(tools=tool_schemas)
    # Silero detects speech boundaries. ElevenLabs' realtime STT uses those
    # boundaries to commit each transcript before Gemini responds.
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
        processor_unusable_policy=ProcessorUnusablePolicy.END,
    )
    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(_transport, _client) -> None:
        logger.info("Browser connected")
        context.add_message(
            {"role": "developer", "content": "Greet the caller briefly and ask how you can help."}
        )
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(_transport, _client) -> None:
        logger.info("Browser disconnected")
        await runner.cancel()

    await runner.run()


async def bot(runner_args: RunnerArguments) -> None:
    """Entry point called by Pipecat's local development runner."""
    transport = await create_transport(runner_args, TRANSPORT_PARAMS)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    # This runner hosts the local Small WebRTC signaling endpoint and its
    # built-in browser client at http://localhost:7860/client/.
    # Pipecat prints Unicode box drawing characters on startup. Use UTF-8 so
    # this also works in a default Windows PowerShell console (often CP1252).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    from pipecat.runner.run import main

    main()

"""Voice-only starter bot: ElevenLabs STT -> Gemini -> ElevenLabs TTS."""

import os
import sys
from pathlib import Path

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
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.workers.runner import WorkerRunner


# Always load the project-root .env, even if this script is run from backend/.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

SYSTEM_INSTRUCTION = (
    "You are a friendly voice assistant. Keep replies short, natural, and easy "
    "to understand when spoken aloud. This starter bot does not book appointments yet."
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
        settings=ElevenLabsRealtimeSTTService.Settings(
            model=os.getenv("ELEVENLABS_STT_MODEL", "scribe_v2_realtime")
        ),
    )

    llm = GoogleLLMService(
        api_key=google_api_key,
        settings=GoogleLLMService.Settings(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
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

    # The context is shared by the LLM and the two conversation aggregators.
    context = LLMContext()
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
            {"role": "developer", "content": "Start with a brief greeting."}
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

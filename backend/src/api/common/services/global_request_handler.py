import os
from pathlib import Path

from backend.src.api.common.enums import (
    FileHelperNames,
    FileRetrievalCodes,
    RequestProcessCodes,
)
from backend.src.api.common.file_helpers import BaseFileHelper
from backend.src.api.common.io_handlers import requests_repository, progress_handler
from backend.src.api.common.request_helpers.helpers_handler import HelpersHandler
from backend.src.api.common.schemas.media_request import MediaRequestDTO
from backend.src.api.common.services.handler_picker import HandlerPicker
from backend.src.api.common.services.request_queue import RequestQueue
from backend.src.api.common.types.file_helper import FileHelper
from backend.src.api.common.types.request import GeneralRequestType
from backend.src.api.common.types.request_handler import RequestHandler
from backend.src.api.common.types.request_helper import RequestHelper
from backend.src.api.common.utils import (
    archive_request_output,
    delete_request_data,
    input_path_from_request_id,
    video_path_from_request_id,
)
from backend.src.api.tasks_handlers.constants import INPUT_FILENAME
from backend.src.app_config import app_config
from backend.src.config.enums import AudioCodecs, VideoCodecs
from backend.src.constants import NULL_PATH
from backend.src.pipeline.schemas.paths import PathsSchema
from backend.src.utils import get_logger_by_filepath

logger = get_logger_by_filepath(__file__)


class GlobalRequestsHandler:
    current_request_id: str = ""

    def __init__(self):
        self.queue: RequestQueue = RequestQueue(app_config.requests_queue_size)
        self.__handler_picker: HandlerPicker = HandlerPicker()
        self._file_helpers: HelpersHandler = HelpersHandler()
        self._helpers: HelpersHandler = HelpersHandler()

    def register_request_handler(self, handler: RequestHandler):
        logger.info(
            "Registering %s handler with file_types=[%s]...",
            handler.event_type,
            ", ".join(map(str, handler.file_types)),
        )
        self.__handler_picker.add_handler(handler)

    async def register_file_helper(self, file_helper: FileHelper):
        logger.info("Initializing %s helper...", file_helper.name)
        await self._file_helpers.register_helper(file_helper)

    async def register_request_helper(self, helper: RequestHelper):
        logger.info("Initializing %s helper...", helper.name)
        await self._helpers.register_helper(helper)

    async def add_request(
        self, request_id: str, request_type: GeneralRequestType, dto: MediaRequestDTO
    ) -> RequestProcessCodes:
        if self.queue.exists(request_id):
            return RequestProcessCodes.ALREADY_QUEUED

        # UploadFile is a only alive while the request is being processed
        # By the time _process_request is called UploadFile is destroyed
        # To fix that file needs to be saved during add_request
        self._request_folders_setup(request_id)
        if dto.file:
            return_code, _ = await self._retrieve_file(
                dto, input_path_from_request_id(request_id)
            )

            if return_code != FileRetrievalCodes.OK:
                delete_request_data(request_id)
                logger.error("Failed to retrieve input file")
                return RequestProcessCodes.FILE_NOT_FOUND

        logger.info("Queued request: %s", request_id)
        success = await self.queue.push(dto, request_type, request_id)
        return RequestProcessCodes.OK if success else RequestProcessCodes.QUEUE_FULL

    async def start(self):
        logger.info("Startup completed")
        while True:
            req, req_type, req_id = await self.queue.pop()
            self.current_request_id = req_id
            try:
                await self._process_request(req, req_id, req_type)
            # pylint: disable=broad-exception-caught
            except Exception as e:
                delete_request_data(req_id)
                request_progress_data = await progress_handler.get_progress_data(req_id)

                status_code: int = requests_repository.CANCELED
                if request_progress_data["current_stage"] > 0:
                    status_code = requests_repository.DONE_PARTIALLY

                requests_repository.update_status(req_id, status_code)
                await progress_handler.request_finished(req_id, status_code)
                logger.error(
                    "Error occurred when processing request %s:\n%s", req_type, e
                )
            # pylint: enable=broad-exception-caught
            self.current_request_id = ""
            self.queue.task_done()

    @staticmethod
    def _request_folders_setup(request_id: str):
        os.makedirs(input_path_from_request_id(request_id).parent, exist_ok=True)
        out_dir: Path = video_path_from_request_id(request_id).parent
        # TODO: Reconsider
        if out_dir.is_dir():
            delete_request_data(request_id, delete_input=False)
        os.makedirs(out_dir)

    async def _process_request(
        self, dto: MediaRequestDTO, request_id: str, request_type: GeneralRequestType
    ) -> RequestProcessCodes:
        logger.info("Starting to process request: %s", request_id)
        requests_repository.processing_started(request_id)

        return_code, input_file_path = await self._retrieve_file(
            dto, input_path_from_request_id(request_id)
        )

        if return_code != FileRetrievalCodes.OK:
            delete_request_data(request_id)
            logger.error("Failed to download input file")
            requests_repository.update_status(request_id, requests_repository.CANCELED)
            return RequestProcessCodes.FILE_NOT_FOUND
        logger.info("Input file retrieved")

        request_handler = self.__handler_picker.pick_handler(
            input_file_path, request_type
        )
        if request_handler is None:
            logger.info("No request handler found for request. Canceled %s", request_id)
            # TODO: More descriptive error
            delete_request_data(request_id)
            requests_repository.update_status(request_id, requests_repository.CANCELED)
            return RequestProcessCodes.UNKNOWN_ERROR

        video_codec: VideoCodecs = app_config.ffmpeg.codecs.video
        if "codecs" in dto.request.config.model_fields:
            video_codec = dto.request.config.codecs.video
        elif "ffmpeg" in dto.request.config:
            video_codec = dto.request.config.ffmpeg.codecs.video

        audio_codec: AudioCodecs = app_config.ffmpeg.codecs.audio
        if "audio" in dto.request.config.model_fields:
            audio_codec = dto.request.config.audio.codec

        await request_handler.handle(
            request_id,
            dto.request,
            self._helpers,
            PathsSchema(input_file_path, request_id, video_codec, audio_codec),
        )
        logger.info("Render complete, deleting input files...")

        # Cleanup input files
        delete_request_data(request_id, delete_output=False)

        logger.info("Archiving request output...")
        archive_request_output(request_id)

        logger.info("Task done: %s", request_id)
        requests_repository.update_status(request_id, requests_repository.FINISHED)
        await progress_handler.request_finished(
            request_id, requests_repository.FINISHED
        )
        return RequestProcessCodes.OK

    async def _retrieve_file(
        self, request_body: MediaRequestDTO, save_path: Path
    ) -> tuple[FileRetrievalCodes, Path]:
        """
        :param request_body:
        :param save_path:
        :return: Path where file was saved. save_path with correct suffix
        """
        # Check if input file is present in directory
        for f in save_path.parent.iterdir():
            if not f.is_file():
                continue
            if f.name.startswith(INPUT_FILENAME):
                return FileRetrievalCodes.OK, save_path.parent / f.name

        helper_name: FileHelperNames | None = FileHelperNames.UPLOAD_FILE
        if request_body.request.url:
            helper_name = FileHelperNames.YADISK
        elif request_body.request.path and app_config.allow_local_files:
            helper_name = FileHelperNames.LOCAL
        elif request_body.request.path:
            helper_name = None

        if not helper_name:
            return FileRetrievalCodes.UNSUPPORTED_METHOD, NULL_PATH

        helper: BaseFileHelper = self._file_helpers.get_helper_by_name(helper_name)
        return await helper.retrieve_file(
            request_body.request.url or request_body.file or request_body.request.path,
            save_path,
        )

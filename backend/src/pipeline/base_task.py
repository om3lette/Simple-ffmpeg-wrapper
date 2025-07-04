from pydantic import BaseModel, Field

from backend.src.api.common.request_helpers.helpers_handler import HelpersHandler
from backend.src.api.common.types.request import CustomRequestActions
from backend.src.pipeline.enums import TaskType
from backend.src.pipeline.schemas.paths import PathsSchema
from backend.src.pipeline.schemas.streams import StreamsSchema
from backend.src.pipeline.types import RenderConfig
from backend.src.pipeline.types.state_callbacks import UpdateProgressCb


class BaseTask(BaseModel):
    type: TaskType
    request_type: CustomRequestActions
    dependencies: list["BaseTask"] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True

    async def execute(
        self,
        config: RenderConfig,
        helpers: HelpersHandler,
        streams: StreamsSchema,
        paths: "PathsSchema",
        update_progress: UpdateProgressCb,
    ):
        return

    @staticmethod
    def extract_config(full_config: RenderConfig) -> RenderConfig:
        """Override in subclass to extract the relevant config."""
        return full_config

    def __hash__(self):
        return hash(
            (
                self.type,
                self.request_type,
                tuple(dep.__class__.__name__ for dep in self.dependencies),
            )
        )

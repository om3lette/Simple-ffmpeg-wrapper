from pydantic import BaseModel, Field

from src.api.common.request_helpers.helpers_handler import HelpersHandler
from src.api.common.types.request import CustomRequestActions
from src.pipeline.enums import TaskType
from src.pipeline.schemas.paths import PathsSchema
from src.pipeline.schemas.streams import StreamsSchema
from src.pipeline.types import RenderConfig


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

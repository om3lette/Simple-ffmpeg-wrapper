from typing import Callable, Awaitable

UpdateStageCb = Callable[[int], Awaitable[None]]
UpdateProgressCb = Callable[[int], Awaitable[None]]

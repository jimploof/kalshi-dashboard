from typing import Annotated

from fastapi import Depends

from app.config import Settings, get_settings

# Reusable type alias: inject(SettingsDep) in any route handler
SettingsDep = Annotated[Settings, Depends(get_settings)]

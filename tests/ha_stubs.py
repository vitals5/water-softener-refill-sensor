"""Minimal Home Assistant test stubs for isolated testing without Home Assistant installed."""
from __future__ import annotations

import importlib.abc
import importlib.util
import sys
import types
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")


# ---------------------------------------------------------------- Automatic stubs
class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return f"{cls.__name__}.{name}"


def _cls(name: str):
    def init(self, *a, **k):
        if a and hasattr(a[0], "__dict__"):
            self.config = a[0].__dict__
        self.__dict__.update(k)

    return _Meta(
        name,
        (object,),
        {
            "__init__": init,
            "__class_getitem__": classmethod(lambda c, i: c),
        },
    )


class _AutoModule(types.ModuleType):
    __path__: list = []

    def __call__(self, *a, **k):
        return _cls("Call")(**k)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name[0].isupper():
            obj = _cls(name)
        else:
            obj = importlib.import_module(f"{self.__name__}.{name}")
        setattr(self, name, obj)
        return obj


class _Loader(importlib.abc.Loader):
    def create_module(self, spec):
        return _AutoModule(spec.name)

    def exec_module(self, module):
        pass


class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name == "voluptuous" or name.startswith("homeassistant"):
            return importlib.util.spec_from_loader(name, _Loader(), is_package=True)
        return None


def _module(name: str, **attrs: Any) -> types.ModuleType:
    mod = _AutoModule(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# ---------------------------------------------------------------- Explicit stubs
class FakeStore:
    DATA: dict[str, Any] = {}

    def __init__(self, hass, version, key, **kw):
        self.key = key

    async def async_load(self):
        return FakeStore.DATA.get(self.key)

    async def async_save(self, data):
        FakeStore.DATA[self.key] = data

    def async_delay_save(self, data_func, delay=0):
        FakeStore.DATA[self.key] = data_func()

    async def async_remove(self):
        FakeStore.DATA.pop(self.key, None)


class FakeCoordinator:
    def __init__(self, hass, logger, *, config_entry=None, name=None, **kw):
        self.data = None
        self.updates = 0

    def async_set_updated_data(self, data):
        self.data = data
        self.updates += 1


class FakeCoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator

    def __class_getitem__(cls, item):
        return cls


class FakeNotifications:
    active: dict[str, dict[str, Any]] = {}
    log: list[tuple] = []

    @classmethod
    def async_create(cls, hass, message, title=None, notification_id=None):
        cls.active[notification_id] = {"title": title, "message": message}
        cls.log.append(("create", notification_id, title))

    @classmethod
    def async_dismiss(cls, hass, notification_id):
        if cls.active.pop(notification_id, None) is not None:
            cls.log.append(("dismiss", notification_id))


class FakeDt:
    _now = datetime(2026, 10, 5, 12, 0, tzinfo=TZ)

    @classmethod
    def now(cls):
        return cls._now

    @staticmethod
    def as_local(d):
        return d.astimezone(TZ)

    @staticmethod
    def as_utc(d):
        return d

    @staticmethod
    def get_default_time_zone():
        return TZ


@dataclass(frozen=True, kw_only=True)
class FakeDescription:
    key: str
    translation_key: str | None = None
    device_class: Any = None
    native_unit_of_measurement: Any = None
    state_class: Any = None
    icon: str | None = None
    entity_category: Any = None
    suggested_display_precision: int | None = None


class FakeConfigFlow:
    def __init_subclass__(cls, domain=None, **kw):
        cls.domain = domain


class ServiceValidationError(Exception):
    pass


def install() -> None:
    """Register stubs in sys.modules."""
    sys.meta_path.append(_Finder())
    _module("homeassistant")
    _module(
        "homeassistant.const",
        STATE_UNAVAILABLE="unavailable",
        STATE_UNKNOWN="unknown",
        PERCENTAGE="%",
        CONF_NAME="name",
        UnitOfMass=_cls("UnitOfMass"),
        UnitOfEnergy=_cls("UnitOfEnergy"),
        UnitOfPower=_cls("UnitOfPower"),
        EntityCategory=_cls("EntityCategory"),
        Platform=_cls("Platform"),
    )
    _module("homeassistant.core", callback=lambda f: f)
    _module("homeassistant.exceptions", ServiceValidationError=ServiceValidationError)
    _module("homeassistant.config_entries", ConfigFlow=FakeConfigFlow)
    _module("homeassistant.helpers")
    _module("homeassistant.helpers.storage", Store=FakeStore)
    _module(
        "homeassistant.helpers.event",
        async_track_state_change_event=lambda hass, ids, action: (
            hass.state_cbs.append((list(ids), action)) or (lambda: None)
        ),
        async_track_time_change=lambda hass, action, hour=None, minute=None, second=None: (
            hass.time_cbs.append((hour, minute, second, action)) or (lambda: None)
        ),
    )
    _module(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=FakeCoordinator,
        CoordinatorEntity=FakeCoordinatorEntity,
    )
    _module("homeassistant.components")
    _module(
        "homeassistant.components.persistent_notification",
        async_create=FakeNotifications.async_create,
        async_dismiss=FakeNotifications.async_dismiss,
    )
    sys.modules["homeassistant.components"].persistent_notification = sys.modules[
        "homeassistant.components.persistent_notification"
    ]
    _module("homeassistant.components.sensor", SensorEntityDescription=FakeDescription)
    _module("homeassistant.components.binary_sensor")
    _module("homeassistant.components.button")
    _module("homeassistant.components.number")
    _module("homeassistant.components.datetime")
    dt_mod = _module(
        "homeassistant.util.dt",
        now=FakeDt.now,
        as_local=FakeDt.as_local,
        as_utc=FakeDt.as_utc,
        get_default_time_zone=FakeDt.get_default_time_zone,
    )
    _module("homeassistant.util", dt=dt_mod)

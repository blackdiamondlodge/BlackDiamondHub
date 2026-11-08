"""Plugin contract for Black Diamond Hub apps.

The contract now lives in the ``bdh-sdk`` package
(github.com/blackdiamondlodge/bdh-sdk), which apps in their own repos depend
on. This module re-exports it so built-in apps can keep importing
``hub.plugins``. Change the contract in bdh-sdk, not here.
"""
from bdh_sdk import *  # noqa: F401,F403
from bdh_sdk import __all__  # noqa: F401

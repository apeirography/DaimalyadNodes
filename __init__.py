from .daimalyad_model_downloader import DaimalyadModelDownloader
from .daimalyad_wildcard_processor import DaimalyadWildcardProcessor

NODE_CLASS_MAPPINGS = {
    "DaimalyadModelDownloader": DaimalyadModelDownloader,
    "DaimalyadWildcardProcessor": DaimalyadWildcardProcessor,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DaimalyadModelDownloader": "Model Downloader (DaimalyadNodes)",
    "DaimalyadWildcardProcessor": "API-Friendly Wildcard Processor (DaimalyadNodes)",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
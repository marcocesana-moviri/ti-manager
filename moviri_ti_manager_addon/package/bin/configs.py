import ipaddress

### GLOBAL CONFIGS ###
ADDON_NAME = "moviri_ti_manager_addon"
ADDON_VERSION = "0.0.1"
CONF_FILE_NAME = "moviri_ti_manager_addon_settings"
CONF_FILE_BASE_NAME = f"{ADDON_NAME.lower()}"
ACCOUNT_CONF_FILE_NAME = f"{CONF_FILE_BASE_NAME}_account"

### LOGGER CONFIGS ###
LOG_DEBUG_TAG = "[TI MANAGER DEBUG]"
LOG_INFO_TAG = "[TI MANAGER INFO]"
LOG_ERROR_TAG = "[TI MANAGER ERROR]"
LOG_WARNING_TAG = "[TI MANAGER WARNING]"
LOG_CRITICAL_TAG = "[TI MANAGER CRITICAL]"

### REQUEST CONFIGS ###
REQUEST_TIMEOUT = 30  
REQUEST_RETRIES = 5
RETRY_BACKOFF_SECONDS = 2 

### KV STORE ###
KVSTORE_LIMIT = 50000
KVSTORE_ADDITION_CHUNK_SIZE = 1000
KVSTORE_DELETION_CHUNK_SIZE = 100

### WHITELIST PRIVATE IPs ###
STATIC_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
]
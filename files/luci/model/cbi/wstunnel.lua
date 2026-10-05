local tunnel_validator = require("wstunnel.tunnel")
local map = Map("wstunnel", "wstunnel", translate("Enabled clients start at boot. Logs: logread -e wstunnel."))
local clients = map:section(TypedSection, "client", translate("Clients"))
clients.addremove = true
clients.anonymous = false

local status_ok, service_status = pcall(require("luci.util").ubus, "service", "list", { name = "wstunnel" })
local status = clients:option(DummyValue, "_status", translate("Process status"))
status.description = translate("Refresh the page to update. A running process does not mean the tunnel is connected.")
function status.cfgvalue(self, section)
    if not status_ok or type(service_status) ~= "table" then
        return translate("Unknown (process status unavailable)")
    end
    local service = service_status.wstunnel
    local instances = type(service) == "table" and service.instances
    local instance = type(instances) == "table" and instances[section]
    if type(instance) == "table" and instance.running == true then
        local pid = tonumber(instance.pid)
        if pid and pid > 0 and pid == math.floor(pid) then
            return translate("Running (PID %s)"):format(string.format("%.0f", pid))
        end
        return translate("Running")
    end
    return translate("Stopped")
end

local enabled = clients:option(Flag, "enabled", translate("Enable"))
enabled.default = "0"
enabled.rmempty = false

local server = clients:option(Value, "server", translate("Server URL"))
server.placeholder = "wss://example.com:443"
server.rmempty = false
function server.validate(self, value)
    if value and not value:find("%s") and (value:match("^https?://[^/]+") or value:match("^wss?://[^/]+")) then
        return value
    end
    return nil, translate("Enter a ws://, wss://, http:// or https:// server URL.")
end

local local_forward = clients:option(DynamicList, "local_forward", translate("Local forwarding tunnels"))
local_forward.placeholder = "tcp://127.0.0.1:51820:127.0.0.1:51820"
local_forward.description = translate(
    "One -L tunnel per line. TCP/UDP: protocol://listen-address:port:destination-address:port. The destination is the service you would connect to directly, not the wstunnel server, and must be reachable from that server."
)
local function validate_tunnel(self, value)
    local values = type(value) == "table" and value or { value }
    for _, tunnel in ipairs(values) do
        if not tunnel_validator.validate(tunnel) then
            return nil, translate("Enter a supported tunnel URI with valid addresses and ports (0-65535).")
        end
    end
    return value
end
local_forward.validate = validate_tunnel
function enabled.validate(self, value, section)
    if value == "1" then
        local tunnels = local_forward:formvalue(section) or {}
        if type(tunnels) == "string" then
            tunnels = { tunnels }
        end
        local valid, error_message = validate_tunnel(self, tunnels)
        if not valid then
            return nil, error_message
        end
        for _, tunnel in ipairs(tunnels) do
            if tunnel ~= "" then
                return value
            end
        end
        return nil, translate("Configure at least one local forwarding tunnel before enabling the client.")
    end
    return value
end

local verify = clients:option(Flag, "tls_verify", translate("Verify TLS certificate"))
verify.default = "1"
verify.rmempty = false
verify.description = translate("Enabled by default. Disable only for a trusted server using a self-signed certificate.")
clients:option(Value, "sni", translate("TLS SNI override"))
local prefix = clients:option(Value, "path_prefix", translate("HTTP upgrade path prefix"))
prefix.placeholder = "v1"
prefix.description = translate(
    "wstunnel automatically appends /events to the prefix. For example, v1 produces the request path /v1/events. If your reverse proxy routes by path, ensure its rule matches and forwards this request to wstunnel; either exact-path or prefix matching works. Enter only the prefix here."
)
local proxy = clients:option(Value, "http_proxy", translate("Upstream HTTP proxy"))
proxy.placeholder = "http://127.0.0.1:8080"
local credentials = clients:option(Value, "credentials", translate("HTTP Basic authentication"))
credentials.password = true
credentials.description = '<span style="white-space: normal">'
    .. translate(
        "Format: USER:PASS. Credentials are stored on the router and readable by administrators; they also appear in process arguments."
    )
    .. "</span>"
local level = clients:option(ListValue, "log_level", translate("Log level"))
for _, value in ipairs({ "TRACE", "DEBUG", "INFO", "WARN", "ERROR", "OFF" }) do
    level:value(value)
end
level.default = "INFO"
local workers = clients:option(Value, "nb_worker_threads", translate("Worker threads"))
workers.datatype = "and(uinteger,min(1))"
workers.description = translate("Sets --nb-worker-threads. Leave blank to use the wstunnel default (CPU count).")
function workers.validate(self, value)
    if value == nil or value == "" or value:match("^%d+$") and value:find("[1-9]") then
        return value
    end
    return nil, translate("Enter a positive integer, or leave blank to use the default.")
end
return map

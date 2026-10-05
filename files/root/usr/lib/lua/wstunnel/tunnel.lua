local M = {}

local function client_accepts(value)
    -- Delegate URL decoding and IDNA to the bundled parser. An unsupported
    -- server scheme stops it after argument parsing, before any tunnel starts.
    local quoted = "'" .. value:gsub("'", "'\\''") .. "'"
    local process = io.popen(
        "NO_COLOR=false /usr/bin/wstunnel client --no-color -L " .. quoted .. " parser-sentinel://127.0.0.1 2>&1"
    )
    if not process then
        return false
    end
    local diagnostic = process:read("*l") or ""
    process:close()
    return diagnostic:match(
        "^error: invalid value 'parser%-sentinel://127%.0%.0%.1' for '<[^>]+>': invalid scheme parser%-sentinel$"
    ) ~= nil
end

local function port(value, local_port)
    local pattern = local_port and "^%+?%d+$" or "^%d+$"
    return value:match(pattern) ~= nil and tonumber(value) <= 65535
end

local function ipv4(value)
    local count = 0
    for octet in (value .. "."):gmatch("(.-)%.") do
        if not octet:match("^%d+$") or #octet > 1 and octet:sub(1, 1) == "0" or tonumber(octet) > 255 then
            return false
        end
        count = count + 1
    end
    return count == 4
end

local function ipv6(value)
    if value:find("[^%x:%.]") then
        return false
    end
    local tail = value:match("([^:]+)$")
    local groups = 0
    if tail and tail:find("%.") then
        if not ipv4(tail) then
            return false
        end
        value = value:sub(1, #value - #tail) .. "0:0"
    end
    local compression = value:find("::", 1, true)
    if value:sub(1, 1) == ":" and value:sub(1, 2) ~= "::" or value:sub(-1) == ":" and value:sub(-2) ~= "::" then
        return false
    end
    if compression then
        if value:find("::", compression + 2, true) or value:find(":::", 1, true) then
            return false
        end
    end
    for group in value:gmatch("[^:]+") do
        if #group > 4 or not group:match("^%x+$") then
            return false
        end
        groups = groups + 1
    end
    return compression ~= nil and groups < 8 or compression == nil and groups == 8
end

local function destination_host(value)
    if value:sub(1, 1) == "[" then
        return value:sub(-1) == "]" and ipv6(value:sub(2, -2))
    end
    if value == "" or value:find("[%c%s/#?@:%[%]\\<>%^|]") then
        return false
    end
    -- v11 uses the URL host parser: a numeric final label denotes IPv4,
    -- including shortened, octal and hexadecimal addresses.
    local host = value:gsub("%.$", "")
    local last = host:match("([^.]+)$") or ""
    if not (last:match("^%d+$") or last:match("^0[xX]%x*$")) then
        return true
    end
    local parts = {}
    for part in (host .. "."):gmatch("(.-)%.") do
        local digits, base = part, 10
        if part:match("^0[xX]") then
            digits, base = part:sub(3), 16
        elseif #part > 1 and part:sub(1, 1) == "0" then
            digits, base = part:sub(2), 8
        end
        local pattern = base == 16 and "^%x+$" or base == 8 and "^[0-7]+$" or "^%d+$"
        if digits == "" and base ~= 10 then
            digits = "0"
        end
        if not digits:match(pattern) then
            return false
        end
        parts[#parts + 1] = tonumber(digits, base)
    end
    if #parts > 4 then
        return false
    end
    for index = 1, #parts - 1 do
        if parts[index] > 255 then
            return false
        end
    end
    return parts[#parts] < 256 ^ (5 - #parts)
end

local function destination(value)
    local host, remote_port = value:match("^(.*):([^:]+)$")
    if not host or not port(remote_port, false) or not destination_host(host) then
        return false
    end
    -- The v11 URL parser drops default HTTPS ports; its fallback recognizes
    -- only the literal spelling :443, so :0443 would fail in the client.
    return tonumber(remote_port) ~= 443 or remote_port == "443"
end

local function local_bind(value)
    local bind, remaining
    if value:sub(1, 1) == "[" then
        bind, remaining = value:match("^%[([^%]]+)%]:(.*)$")
        if not bind or not ipv6(bind) then
            return nil
        end
    else
        bind, remaining = value:match("^([^:]+):(.*)$")
        if not bind or not ipv4(bind) then
            remaining = value
        end
    end
    local local_port, remote = remaining:match("^([^:]+):(.*)$")
    local_port = local_port or remaining
    if not port(local_port, true) then
        return nil
    end
    return remote or ""
end

function M.validate(value)
    if type(value) ~= "string" or value:find("%z") then
        return false
    end
    -- Query options are intentionally left to wstunnel (timeout, proxy
    -- credentials, etc.); only address and port syntax is validated here.
    local address = value:match("^([^?]*)")
    local protocol, remaining = address:match("^([%w]+)://(.+)$")
    if
        protocol ~= "unix"
        and protocol ~= "tcp"
        and protocol ~= "udp"
        and protocol ~= "socks5"
        and protocol ~= "http"
    then
        return false
    end
    local path, unix_remote
    if protocol == "unix" then
        path, unix_remote = remaining:match("^([^:]+):(.*)$")
        if not path then
            return false
        end
    end
    if value:find("[\128-\255%%]") or remaining:lower():find("xn--", 1, true) then
        return client_accepts(value)
    end
    if protocol == "unix" then
        return destination(unix_remote)
    end
    local remote = local_bind(remaining)
    if remote == nil then
        return false
    end
    if protocol == "socks5" or protocol == "http" then
        return remote == ""
    end
    return destination(remote)
end

return M

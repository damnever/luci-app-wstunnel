local options = {}
function translate(value)
    return value
end
local service_status = {}
local query_failure = false
package.preload["luci.util"] = function()
    return {
        ubus = function(object, method, arguments)
            assert(object == "service" and method == "list" and arguments.name == "wstunnel")
            if query_failure then
                error("ubus unavailable")
            end
            return service_status
        end,
    }
end
DummyValue = "DummyValue"
Flag, Value, DynamicList, ListValue, TypedSection = "Flag", "Value", "DynamicList", "ListValue", "TypedSection"
function Map(name, title, description)
    assert(name == "wstunnel")
    return {
        description = description,
        section = function()
            return {
                option = function(self, kind, key, label)
                    local option = { kind = kind, label = label }
                    function option:value() end
                    function option:formvalue(section)
                        return self.input
                    end
                    options[key] = option
                    return option
                end,
            }
        end,
    }
end
dofile("files/luci/model/cbi/wstunnel.lua")
assert(options._status:cfgvalue("main") == "Stopped")
service_status.wstunnel = { instances = { main = { running = true, pid = 123 }, other = { running = false } } }
assert(options._status:cfgvalue("main") == "Running (PID 123)")
assert(options._status:cfgvalue("other") == "Stopped")
assert(options._status:cfgvalue("missing") == "Stopped")
service_status.wstunnel.instances.main.pid = nil
assert(options._status:cfgvalue("main") == "Running")
query_failure = true
dofile("files/luci/model/cbi/wstunnel.lua")
assert(options._status:cfgvalue("main") == "Unknown (process status unavailable)")
query_failure = false
service_status = nil
dofile("files/luci/model/cbi/wstunnel.lua")
assert(options._status:cfgvalue("main") == "Unknown (process status unavailable)")
service_status = {}
dofile("files/luci/model/cbi/wstunnel.lua")
assert(options.enabled.default == "0")
assert(options.tls_verify.default == "1")
assert(options.credentials.password)
assert(options.remote_forward == nil)
assert(options.nb_worker_threads.default == nil)
for _, value in ipairs({ "", "1", "2", "04" }) do
    assert(options.nb_worker_threads:validate(value) == value)
end
for _, value in ipairs({ "0", "00", "-1", "1.5", "abc" }) do
    assert(options.nb_worker_threads:validate(value) == nil)
end
for _, url in ipairs({ "ws://localhost:80", "wss://example.com", "https://[::1]:443", "http://example.org" }) do
    assert(options.server:validate(url) == url)
end
for _, url in ipairs({ "--help", "wss://", "ssh://example.org", "wss:// bad", "wss://example.org bad" }) do
    assert(options.server:validate(url) == nil)
end
for _, uri in ipairs({
    "tcp://127.0.0.1:1234:localhost:80",
    "udp://1234:localhost:53",
    "socks5://[::1]:1080",
    "http://127.0.0.1:8080",
    "unix:///tmp/test.sock:localhost:80",
}) do
    assert(options.local_forward:validate(uri) == uri)
end
assert(options.local_forward:validate("stdio://localhost:80") == nil)
assert(options.local_forward:validate("tcp://") == nil)
local tunnels = { "tcp://127.0.0.1:1234:localhost:80", "udp://1234:localhost:53" }
assert(options.local_forward:validate(tunnels) == tunnels)
assert(options.local_forward:validate({ "tcp://1234:localhost:80", "invalid" }) == nil)
assert(options.enabled:validate("0", "main") == "0")
assert(options.enabled:validate("1", "main") == nil)
options.local_forward.input = tunnels
assert(options.enabled:validate("1", "main") == "1")
options.local_forward.input = {}
assert(options.enabled:validate("1", "main") == nil)
print("LuCI CBI configuration and validation tests passed")

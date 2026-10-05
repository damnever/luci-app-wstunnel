module("luci.controller.wstunnel", package.seeall)

function index()
    if not nixio.fs.access("/etc/config/wstunnel") then
        return
    end
    local page = entry({ "admin", "services", "wstunnel" }, cbi("wstunnel"), "wstunnel", 90)
    page.dependent = true
    page.acl_depends = { "luci-app-wstunnel" }
end

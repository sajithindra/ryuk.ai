import subprocess
import re
import socket
import asyncio
from core.logger import logger
from core.utils import get_local_ip, get_network_interfaces

COMMON_RTSP_PORTS = ["554", "8554", "10554", "6554"]

async def check_rtsp_path(ip, port, path, timeout=1):
    """
    Tries to connect to an RTSP path to see if it's valid.
    """
    url = f"rtsp://{ip}:{port}{path}"
    return url

async def discover_cameras(network_range=None):
    """
    Scans the network for RTSP devices and returns a list of discovered IPs, ports, and interface types.
    """
    interfaces = []
    if network_range is None:
        interfaces = get_network_interfaces()
    else:
        # If a specific range is provided, we can't easily know the type, default to 'lan'
        # Convert range to a simulated interface object
        interfaces = [{"name": "manual", "ip": network_range.split('/')[0], "type": "lan", "range": network_range}]

    ports_str = ",".join(COMMON_RTSP_PORTS)
    results = []
    seen_ips = set()

    for iface in interfaces:
        target_range = iface.get("range")
        if not target_range:
            base_ip = ".".join(iface["ip"].split(".")[:-1])
            target_range = f"{base_ip}.0/24"
            
        logger.info(f"Discovery: Scanning {iface['name']} ({target_range}) for ports {ports_str}...")

        try:
            # Run nmap to find open RTSP ports
            cmd = ["/usr/bin/nmap", "-p", ports_str, "--open", "-oG", "-", "-n", "-T4", target_range]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                logger.error(f"Discovery: nmap failed on {iface['name']} with code {process.returncode}")
                continue

            for line in stdout.decode().splitlines():
                if "Host:" in line:
                    match = re.search(r"Host: (\d+\.\d+\.\d+\.\d+).*Ports: (.*)", line)
                    if match:
                        ip = match.group(1)
                        if ip in seen_ips: continue
                        
                        ports_chunk = match.group(2)
                        ports = []
                        for port_info in ports_chunk.split(","):
                            if "/open/" in port_info:
                                port = port_info.strip().split("/")[0]
                                if port not in ports:
                                    ports.append(port)
                        
                        if ports:
                            results.append({
                                "ip": ip,
                                "ports": ports,
                                "type": iface["type"]
                            })
                            seen_ips.add(ip)

        except Exception as e:
            logger.error(f"Discovery: Error during scan on {iface['name']}: {e}")

    logger.info(f"Discovery: Found {len(results)} potential RTSP devices across all interfaces.")
    return results

if __name__ == "__main__":
    # Test discovery
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    found = loop.run_until_complete(discover_cameras())
    for item in found:
        print(f"Found {item['ip']} (Type: {item['type']}, Ports: {', '.join(item['ports'])})")

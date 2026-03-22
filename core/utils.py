import subprocess
import socket
import re
from core.logger import logger

def get_local_ip():
    """Returns the primary local IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def scan_network_for_rtsp(network_range=None, additional_ports=None):
    """
    Scans the network for devices with RTSP ports open.
    Returns a list of IP addresses.
    """
    if network_range is None:
        local_ip = get_local_ip()
        base_ip = ".".join(local_ip.split(".")[:-1])
        network_range = f"{base_ip}.0/24"
    
    # Common RTSP ports
    ports = ["554"]  # Standard RTSP port
    if additional_ports:
        ports.extend(additional_ports)
    ports_str = ",".join(ports)
    
    print(f"Scanning network {network_range} for RTSP ports ({ports_str})...")
    
    try:
        # -p ports: scan multiple ports
        # --open: only show open ports
        # -oG -: greppable output to stdout
        # -n: skip DNS resolution
        # -T4: aggressive timing (faster)
        cmd = ["nmap", "-p", ports_str, "--open", "-oG", "-", "-n", "-T4", network_range]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
        
        # Parse greppable output
        ips = []
        for line in result.stdout.splitlines():
            if "Host:" in line and any(f"{port}/open" in line for port in ports):
                match = re.search(r"Host: (\d+\.\d+\.\d+\.\d+)", line)
                if match:
                    ips.append(match.group(1))
        
        logger.info(f"Found {len(ips)} devices with RTSP ports open")
        return ips
    except subprocess.TimeoutExpired:
        logger.warning("Network scan timed out")
        return []
    except Exception as e:
        logger.error(f"Discovery error: {e}")
        return []

#!/usr/bin/env python3
import subprocess
import xml.etree.ElementTree as ET
import socket
import os
import sys
import argparse
import json

class NetworkScanner:
    def __init__(self):
        self.common_camera_ports = [554, 80, 8080, 8000, 8081, 88, 8899, 37777]
        self.rtsp_port = 554
        self.camera_keywords = ["camera", "ipc", "ipcam", "hikvision", "dahua", "axis", "vivotek", "hanwha", "amcrest", "reolink", "onvif"]

    def get_local_network(self):
        """Attempts to find the local network subnet."""
        try:
            # Create a socket to find the IP used for external traffic
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            
            # Assume a /24 network for simplicity (common for home/small office)
            subnet = ".".join(local_ip.split(".")[:-1]) + ".0/24"
            return subnet, local_ip
        except Exception as e:
            print(f"Error detecting local network: {e}")
            return None, None

    def scan_network(self, target_network):
        """Runs nmap to find hosts and services."""
        ports_str = ",".join(map(str, self.common_camera_ports))
        print(f"[*] Scanning network {target_network} for devices and ports: {ports_str}...")
        
        # -sn: Host discovery (ping scan)
        # -p: Specific ports to scan
        # -sV: Service version detection
        # -oX: Output as XML
        # --open: Only show open ports
        cmd = ["nmap", "-sn", target_network]
        print("[*] Performing host discovery...")
        
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            # Find active hosts for targeted service scan
            # This is more efficient for larger networks
            active_hosts = []
            for line in res.stdout.splitlines():
                if "Nmap scan report for" in line:
                    ip = line.split()[-1].strip("()")
                    active_hosts.append(ip)
            
            if not active_hosts:
                print("[!] No active hosts found.")
                return None

            print(f"[*] Found {len(active_hosts)} active hosts. Detailed service scan starting...")
            
            # Now scan only active hosts for efficiency
            cmd_v = ["nmap", "-p", ports_str, "-sV", "--open", "-oX", "-"] + active_hosts
            res_v = subprocess.run(cmd_v, capture_output=True, text=True)
            return res_v.stdout
        except FileNotFoundError:
            print("[!] Nmap not found. Please install nmap: sudo apt install nmap")
            sys.exit(1)
        except Exception as e:
            print(f"[!] Error during scan: {e}")
            return None

    def parse_results(self, xml_output):
        """Parses the XML output from nmap."""
        if not xml_output:
            return []

        try:
            root = ET.fromstring(xml_output)
            devices = []
            
            for host in root.findall("host"):
                addr_node = host.find("address[@addrtype='ipv4']")
                ip = addr_node.get("addr") if addr_node is not None else "Unknown"
                
                hostname_node = host.find("hostnames/hostname")
                hostname = hostname_node.get("name") if hostname_node is not None else ""
                
                mac_node = host.find("address[@addrtype='mac']")
                mac = mac_node.get("addr") if mac_node is not None else "Unknown"
                vendor = mac_node.get("vendor") if mac_node is not None else ""
                
                ports = []
                for port_node in host.findall("ports/port"):
                    portid = port_node.get("portid")
                    state = port_node.find("state").get("state")
                    service_node = port_node.find("service")
                    service_name = service_node.get("name") if service_node is not None else ""
                    product = service_node.get("product") if service_node is not None else ""
                    version = service_node.get("version") if service_node is not None else ""
                    
                    ports.append({
                        "port": portid,
                        "state": state,
                        "name": service_name,
                        "product": product,
                        "version": version
                    })
                
                device_type = "Other Device"
                # Classification logic
                is_camera = any(kw in (hostname + vendor + str(ports)).lower() for kw in self.camera_keywords)
                has_rtsp = any(p["port"] == "554" or "rtsp" in p["name"].lower() for p in ports)
                
                if has_rtsp:
                    device_type = "RTSP Camera"
                elif is_camera:
                    device_type = "Other Camera/Streamer"
                
                devices.append({
                    "ip": ip,
                    "hostname": hostname,
                    "mac": mac,
                    "vendor": vendor,
                    "ports": ports,
                    "type": device_type
                })
            
            return devices
        except Exception as e:
            print(f"[!] Error parsing XML: {e}")
            return []

    def display_results(self, devices):
        """Prints the scan results in a clean table format."""
        if not devices:
            print("[!] No devices with relevant ports found.")
            return

        print("\n" + "="*80)
        print(f"{'IP ADDRESS':<15} | {'TYPE':<20} | {'HOSTNAME/VENDOR':<30} | {'PORTS'}")
        print("-" * 80)
        
        rtsp_count = 0
        camera_count = 0
        total_devices = len(devices)

        for d in devices:
            ports_summary = ", ".join([p["port"] for p in d["ports"]]) or "None discovered"
            name = d["hostname"] or d["vendor"] or "Unknown"
            print(f"{d['ip']:<15} | {d['type']:<20} | {name[:30]:<30} | {ports_summary}")
            
            if d["type"] == "RTSP Camera":
                rtsp_count += 1
            if "Camera" in d["type"]:
                camera_count += 1

        print("="*80)
        print("\n--- Summary ---")
        print(f"Total Active Devices Found: {total_devices}")
        print(f"RTSP Cameras Detected:      {rtsp_count}")
        print(f"Other Streaming Devices:    {camera_count - rtsp_count}")
        print("="*80)

def main():
    parser = argparse.ArgumentParser(description="Scan local network for RTSP cameras and streaming devices.")
    parser.add_argument("--network", help="Target network in CIDR format (e.g., 192.168.1.0/24)")
    args = parser.parse_args()

    scanner = NetworkScanner()
    
    target_network = args.network
    if not target_network:
        target_network, local_ip = scanner.get_local_network()
        if target_network:
            print(f"[*] Auto-detected local network: {target_network} (Your IP: {local_ip})")
        else:
            print("[!] Could not auto-detect network. Please provide --network <range>")
            sys.exit(1)

    xml_output = scanner.scan_network(target_network)
    devices = scanner.parse_results(xml_output)
    scanner.display_results(devices)

if __name__ == "__main__":
    main()

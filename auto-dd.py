import os
import argparse
import re
import ipaddress
import subprocess
import shlex
from time import sleep
import socket
import json
import datetime
import logging

parser = argparse.ArgumentParser(description='Auto dd')
parser.add_argument('--dd-url',
                    required=True,
                    help='dd image url, tar gzip compressed')
parser.add_argument('--interface',
                    required=True,
                    help='interface')
parser.add_argument('--ip-addr',
                    required=True,
                    help='ip cidr address')
parser.add_argument('--ip-gateway',
                    required=True,
                    help='ip gateway')
parser.add_argument('--dns',
                    default="8.8.8.8",
                    help='dns server')
# parser.add_argument('-p', '--password',
#                     default="auto-dd",
#                     help='set root password. dd mode is not need')
parser.add_argument('-v', '--verbose',
                    action='store_true',
                    help='Verbose mode, print debug')
parser.add_argument('--dry-run',
                    action='store_true',
                    help='')
args = parser.parse_args()

logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, 
                    format='%(asctime)s %(levelname)s %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

def run_cmd(cmd, force_run=False):
    if not force_run and args.dry_run:
        return True
    res = subprocess.run(shlex.split(cmd))
    return res.returncode == 0

def check_dependence(bin_str):
    bins = [e.strip() for e in bin_str.split(',')]
    for bin in bins:
        if not run_cmd(f'which {bin}'):
            logging.error(f'need {bin} to run')
            exit(1)

linux_relese = 'debian'
def download_linux(hd_media=False, force=True):
    LinuxMirror = "http://deb.debian.org/debian"
    DIST = "bookworm"
    VER = "amd64"
    legacy = "legacy-" if DIST=="focal" else ""
    inUpdate = ""
    
    if hd_media:
        initrd_url = f"{LinuxMirror}/dists/{DIST}/main/installer-{VER}/current/images/hd-media/initrd.gz"
        vmlinuz_url = f"{LinuxMirror}/dists/{DIST}/main/installer-{VER}/current/images/hd-media/vmlinuz"
    else:
        initrd_url = f"{LinuxMirror}/dists/{DIST}/main/installer-{VER}/current/{legacy}images/netboot/{linux_relese}-installer/{VER}/initrd.gz"
        vmlinuz_url = f"{LinuxMirror}/dists/{DIST}{inUpdate}/main/installer-{VER}/current/{legacy}images/netboot/{linux_relese}-installer/{VER}/linux"

    path = "/boot/initrd.img.new"
    if force or not os.path.exists(path):
        if not run_cmd(f'wget --no-check-certificate -qO "{path}" "{initrd_url}"'):
            logging.error('wget initrd.img failed')
            exit(1)
    path = "/boot/vmlinuz.new"
    if force or not os.path.exists(path):
        if not run_cmd(f'wget --no-check-certificate -qO "{path}" "{vmlinuz_url}"'):
            logging.error('wget vmlinuz failed')
            exit(1)

def download_iso(force=False):
    iso_url = "https://cdimage.debian.org/debian-cd/current/amd64/iso-dvd/debian-12.4.0-amd64-DVD-1.iso"
    path = "/debian-12.4.0-amd64-DVD-1.iso"
    if force or not os.path.exists(path):
        if not run_cmd(f'wget --no-check-certificate -qO "{path}" "{iso_url}"'):
            logging.error('wget iso failed')
            exit(1)

def modify_grub():
    grub_cfg = '/boot/grub/grub.cfg'
    if not os.path.exists('/boot/grub/grub.cfg.bak'):
        run_cmd(f"cp /boot/grub/grub.cfg /boot/grub/grub.cfg.bak")
    run_cmd(f"chmod 664 /boot/grub/grub.cfg")
    
    # replace first menuentry
    with open(grub_cfg, 'r') as f:
        grub = f.read()
        domain = "lan"
        BOOT_OPTION=f"auto=true hostname=debian domain={domain} quiet"
        grub = re.sub(r'linux\s+\/boot\/vmlinuz.*', f'linux /boot/vmlinuz.new {BOOT_OPTION}', grub, count=1)
        grub = re.sub(r'initrd\s+\/boot\/initrd.*', f'initrd /boot/initrd.img.new', grub, count=1)
    with open(grub_cfg, 'w') as f:
        f.write(grub)
    run_cmd(f"chown root:root /boot/grub/grub.cfg")
    run_cmd(f"chmod 444 /boot/grub/grub.cfg")

def modify_initrd():
    if os.path.exists('/tmp/boot'):
        run_cmd('rm -rf /tmp/boot')
    os.mkdir('/tmp/boot')
    os.chdir('/tmp/boot')
    os.system(f"gzip -d < /boot/initrd.img.new | cpio --extract --verbose --make-directories --no-absolute-filenames >>/dev/null 2>&1")
        # logging.error('uncompress initrd.img failed')
        # exit(1)
    
    INTERFACE=args.interface  # or "auto"
    cidr = ipaddress.ip_network(args.ip_addr, strict=False)
    IPv4 = args.ip_addr.split('/')[0]
    MASK = str(cidr.netmask)
    GATEWAY = args.ip_gateway
    DNS = "8.8.8.8"
    
    HOSTNAME = "debian"
    DOMAIN = "op1"
    MirrorHost = "deb.debian.org"
    MirrorFolder = "/debian"
    PASSWORD = "$1$ejcszWiG$9Ka8zO.runHjtCdxSRbX.." # openssl passwd -1 "auto-dd"

    output = subprocess.run(shlex.split(f'ls -1 ./lib/modules 2>/dev/null'), capture_output=True, text=True).stdout.strip()
    kernel_version = re.search(r"\d+.*", output).group()
    SelectLowmem = f"di-utils-exit-installer,driver-injection-disk-detect,fdisk-udeb,netcfg-static,parted-udeb,partman-auto,partman-ext3,ata-modules-{kernel_version}-di,efi-modules-{kernel_version}-di,sata-modules-{kernel_version}-di,scsi-modules-{kernel_version}-di,scsi-nic-modules-{kernel_version}-di,virtio-modules-${kernel_version}"
    IncDisk = "default"
    
    DDURL = args.dd_url
    sshPORT = 22
    setCMD = ""
    
    preseed_cfg1 = f'''\
#_preseed_V1
#### Contents of the preconfiguration file (for bookworm)
### Localization
d-i debian-installer/locale string en_US.UTF-8
d-i debian-installer/country string US
d-i debian-installer/language string en
d-i keyboard-configuration/xkb-keymap string us

d-i keyboard-configuration/xkb-keymap string us
d-i lowmem/low note
d-i anna/choose_modules_lowmem multiselect {SelectLowmem}

### Network configuration
# netcfg will choose an interface that has link if possible. This makes it
# skip displaying a list if there is more than one interface.
d-i netcfg/choose_interface select auto
#d-i netcfg/choose_interface select {INTERFACE}
d-i netcfg/disable_autoconfig boolean true
d-i netcfg/dhcp_failed note
d-i netcfg/dhcp_options select Configure network manually
d-i netcfg/get_ipaddress string {IPv4}
d-i netcfg/get_netmask string {MASK}
d-i netcfg/get_gateway string {GATEWAY}
d-i netcfg/get_nameservers string {DNS}
d-i netcfg/confirm_static boolean true
d-i netcfg/get_hostname string {HOSTNAME}
d-i netcfg/get_domain string {DOMAIN}
# Disable that annoying WEP key dialog.
d-i netcfg/wireless_wep string

# If you want to completely disable firmware lookup (i.e. not use firmware
# files or packages that might be available on installation images):
d-i hw-detect/firmware-lookup string never
# If non-free firmware is needed for the network or other hardware, you can
# configure the installer to always try to load it, without prompting. Or
# change to false to disable asking.
d-i hw-detect/load_firmware boolean true

d-i mirror/country string manual
d-i mirror/http/hostname string {MirrorHost}
d-i mirror/http/directory string {MirrorFolder}
d-i mirror/http/proxy string

d-i passwd/root-login boolean ture
d-i passwd/make-user boolean false
d-i passwd/root-password password r00tme
d-i passwd/root-password-again password r00tme
d-i user-setup/allow-password-weak boolean true
d-i user-setup/encrypt-home boolean false

d-i clock-setup/utc boolean true
d-i time/zone string US/Eastern
d-i clock-setup/ntp boolean false

### Network console
# Use the following settings if you wish to make use of the network-console
# component for remote installation over SSH. This only makes sense if you
# intend to perform the remainder of the installation manually.
d-i anna/choose_modules string network-console
#d-i network-console/authorized_keys_url string http://10.0.0.1/openssh-key
d-i network-console/password password r00tme
d-i network-console/password-again password r00tme

d-i preseed/early_command string anna-install network-console libfuse2-udeb fuse-udeb ntfs-3g-udeb libcrypto1.1-udeb libpcre2-8-0-udeb libssl1.1-udeb libuuid1-udeb zlib1g-udeb wget-udeb
    '''
    
    preseed_cfg = f'''\
    d-i debian-installer/locale string en_US.UTF-8
    d-i debian-installer/country string US
    d-i debian-installer/language string en
    d-i keyboard-configuration/xkb-keymap string us
    
    #d-i netcfg/choose_interface select auto
    d-i netcfg/choose_interface select {INTERFACE}
    d-i netcfg/disable_autoconfig boolean true
    d-i netcfg/dhcp_failed note
    d-i netcfg/dhcp_options select Configure network manually
    d-i netcfg/get_ipaddress string {IPv4}
    d-i netcfg/get_netmask string {MASK}
    d-i netcfg/get_gateway string {GATEWAY}
    d-i netcfg/get_nameservers string {DNS}
    d-i netcfg/confirm_static boolean true
    d-i netcfg/get_hostname string {HOSTNAME}
    d-i netcfg/get_domain string {DOMAIN}
    # Disable that annoying WEP key dialog.
    d-i netcfg/wireless_wep string

    d-i anna/choose_modules string network-console
    #d-i network-console/authorized_keys_url string http://10.0.0.1/openssh-key
    d-i network-console/password password r00tme
    d-i network-console/password-again password r00tme
    
    d-i preseed/early_command string anna-install network-console
    '''
    
    # with open('preseed.cfg', 'r') as f:
    #     preseed_cfg = f.read()
    # preseed_cfg = preseed_cfg.format()
    
    with open('/tmp/boot/preseed.cfg', 'w') as f:
        f.write(preseed_cfg)
    
    run_cmd(f"cp /boot/initrd.img.new /tmp/initrd.img.new")  # save origin initrd.img
    os.system(f"find . | cpio -H newc --create --verbose | gzip -9 > /boot/initrd.img.new")

check_dependence("wget,awk,grep,sed,cut,cat,lsblk,cpio,gzip,find,dirname,basename")
offline = True
ssh = True  # network console
modify_grub()
if offline:
    download_linux(hd_media=True)
    # download iso to root
    download_iso()
    modify_initrd()
else:
    download_linux()
    modify_initrd()
# run_cmd("reboot")
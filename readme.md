
*由于目前时间有限，暂时仅挖一个坑，等之后真的要重装时再完善实现。auto-dd.py目前实现了开启network-console*

## 介绍

起因是想给一个x86的小机器重装PVE，但是不想麻烦地连接键盘和显示器。于是想到能不能将一个磁盘镜像dd到物理磁盘上来重装系统（这是一种常见的复制一个系统到多台机器的方法）。但是由于原系统占用了系统盘，因此没办法直接dd系统盘。接着想到U盘运行live cd安装系统时，系统的文件系统是挂载在内存的，因此可以操作所有磁盘。那么能不能想办法让现有系统重启进入一个live cd环境，然后通过网络远程访问这个live cd系统呢？live cd系统如果可以自动dhcp获得地址，那么感觉就是可行的。所以问题被提炼为：

有一个台运行任意GNU/Linux的headless（没有键盘和显示器）机器被关在一个房间里，可以通过网络ssh登录，有没有可能仅通过网络将其重装为其它系统（比如ubuntu, debian甚至是Windows）？
- 机器没有IPMI远程管理功能
- 机器所在网络是个人控制的局域网，可以自由配置
- 机器使用uefi启动，使用grub引导程序

后面在群聊中询问这个问题，没想到居然是个基本操作，github上还有开源的项目。该项目主要用途是自动将VPS服务器重装为别的系统。

之后我仔细研究了下该项目，发现实际原理更加巧妙，涉及到了**debian-installer**的自动化安装机制(**preseeding**)。并且也让我重新了解了安装一个linux系统过程中，底层究竟做了哪些事情。

最后我想自己重新实现一个类似工具，第一是为了学习（造轮子）。第二是我的需求稍有不同。原本项目中dd安装方式，仅用于安装Windows。而我想实现的是：
1. 通过虚拟机安装任何系统
2. 导出虚拟机磁盘镜像
3. dd安装到物理机上

以上流程的好处是安装虚拟机时可以自定义任意配置，保证结果是满足自己需求的。

## 需求

- 自动dd安装指定镜像
  - 镜像放在网盘
  - 镜像放在lan，开启http服务
  - ~~镜像放在目标机器~~
- 调试模式：开启网络shell，从而可以自定义操作
- ~~自动化安装标准ubuntu, debian系统~~

自动安装ubuntu, centos等系统兼容性不能保证。ubuntu,debian使用preseed.cfg配置文件，centos使用ks.cfg文件，没那么多精力去更新。所以PVE安装好系统（设置好ip，ssh），然后dd安装是比较好的选择。
- 可以使用第三方preseeding服务

镜像放在目标机器的话，dd时需要先载入内存，大概率容量不够，故方案不可行


## 实现

--ip-*
有无网络时均需要有已知ip
- vps：静态ip
- lan：dhcp或静态ip

--have-network
有网络
- 使用netinst，无需ISO
- 额外需要配置mirror，否则无法安装network-console
无网络
- 使用hd media，提前下载好ISO到目标机器

preseeding方式：
- initrd：全部支持
  - 但是可能导致安全启动失败？
- kernel cmdline + network preseeding
  - kernel cmdline: auto, netcfg(interface, dhcp or static ip, hostname, domain)
  - network:
    - install and start network-console
    - umount disk (hd media)
    - `wget -qO- "http://192.168.35.254:8000/pve.img.gz" |gunzip -dc |/bin/dd of=$(list-devices disk |head -n1);`
    - reboot

疑问
- debian-installer中不知道如何安装zstd，gzip压缩dd.image速度有点慢，换成zstd速度更快

## 原理

d-i按照顺序提问
- 问题分为low, medium, high等priority（如设置网络、分区是high，语言、键盘是medium）
- 设置priority后，只会问大于等于priority的问题，默认是high

设置了preseeding文件（initrd或url），则会尝试自动回答

根据preseeding文件位置，可以分为initrd, file(iso, usb), network url 三种preseeding方式。（另外再加上一个kernel cmdline方式）
- initrd：可以自动话任何问题
- kernel cmdline：任何问题，但是cmdline总长度不能超过255
- file：iso-scan前的问题需要手动
- network：网络配置前的问题

对于file和network preseeding
- 设置auto：这样语言，键盘等问题不会再问
- 网络通过kernel cmdline设置：这样即使是network preseeding，也不需要手动回答问题

## 参考

- 参考了[veip007/dd](https://github.com/veip007/dd/tree/master)实现
#!/bin/env python3

import os
import sys
import yaml
import argparse
import shutil
from concurrent.futures import ThreadPoolExecutor


par = argparse.ArgumentParser()
par.add_argument("-c", "--config", help="config file for repo", default=None, required=True)
par.add_argument("-r", "--repo", help="name of repo", default=None, required=True)
par.add_argument("-p", "--project", help="name of project", default=None, required=True)
par.add_argument("-f", "--logfile", help="not in repo rpm list file", default=None, required=True)
args = par.parse_args()


def git_clone(git_url, repo_name, branch):
    """
    git clone gitee repo
    """
    repo_path = os.path.join(os.getcwd(), repo_name)
    if os.path.exists(repo_path):
        shutil.rmtree(repo_path)
    cmd = "git clone --depth 1 %s -b %s" % (git_url, branch)
    if os.system(cmd) != 0:
        print("Git clone %s failed!" % repo_name)
        sys.exit(1)
    else:
        print("Git clone %s success!" % repo_name)
    return repo_path

def get_release_pkg_list():
    """
    get release pkg list
    """
    release_pkglist = []
    repo_name = "release-management"
    git_url = f"https://gitee.com/openeuler/{repo_name}.git"
    repo_path = git_clone(git_url, repo_name, "master")
    if args.project == "openEuler:Mainline":
        branch = "master"
    elif args.project.endswith(":Epol"):
        branch = args.project.replace(":Epol", "").replace(":", "-")
        path_name = ["epol"]
    else:
        branch = args.project.replace(":", "-")
        path_name = ["baseos", "everything-exclude-baseos"]
    for name in path_name:
        yaml_path = os.path.join(repo_path, branch, name, "pckg-mgmt.yaml")
        if os.path.exists(yaml_path):
            with open(yaml_path, "r", encoding="utf-8") as f:
                result = yaml.load(f, Loader=yaml.FullLoader)
            for pckg in result['packages']:
                if pckg['name'] not in release_pkglist:
                    release_pkglist.append(pckg['name'])
    shutil.rmtree(repo_path)
    return release_pkglist

def get_exclude_rpm_list():
    """
    get oemaker exclude rpm list
    """
    exclude_rpmlist = []
    if args.project == "openEuler:Mainline" or args.project == "openEuler:Epol":
        branch = "master"
    elif args.project.endswith(":Epol"):
        branch = args.project.replace(":Epol", "").replace(":", "-")
    else:
        branch = args.project.replace(":", "-")
    repo_name = "oemaker"
    git_url = f"https://gitee.com/src-openeuler/{repo_name}.git"
    repo_path = git_clone(git_url, repo_name, branch)
    cmd = "xmllint --xpath \"//packagelist[@type='exclude']/node()\" %s/rpmlist.xml \
            | grep packagereq | cut -d '>' -f 2 | cut -d '<' -f 1" % repo_path
    ret = os.popen(cmd).read().split('\n')
    exclude_rpmlist = [ x for x in ret if x != "" ]
    shutil.rmtree(repo_path)
    print("oemaker rpmlist.xml exclude rpm:%s" % exclude_rpmlist)
    return exclude_rpmlist

def get_repo_rpm_list():
    """
    get repo all rpms
    """
    tmp_path = "/tmp/_repo_rpm"
    if os.path.exists(tmp_path):
        shutil.rmtree(tmp_path)
    cmd = "yum list --installroot=%s --available -c %s --repo %s | grep %s | awk '{print $1,$2}'" % (tmp_path, args.config, args.repo, args.repo)
    output = os.popen(cmd).read().split('\n')
    result = [ x for x in output if x != "" ]
    if result:
        del(result[0])
    repo_rpm_list = []
    arch_list = [".aarch64", ".x86_64", ".noarch", ".src"]
    for line in result:
        tmp = line.split()
        for arch in arch_list:
            if arch in tmp[0]:
                new_tmp = tmp[0].split(arch)
                name = new_tmp[0]
                if ":" in tmp[1]:
                    version = tmp[1].split(":")[1]
                else:
                    version = tmp[1]
                rpm_name = f"{name}-{version}{arch}.rpm"
                break
        if rpm_name not in repo_rpm_list:
            repo_rpm_list.append(rpm_name)
    return repo_rpm_list

def get_pkg_rpms(pkg, arch, pkg_rpm_list):
    """
    get a package all rpm
    """
    cmd = f"osc ls -b {args.project} {pkg} standard_{arch} {arch} 2>/dev/null | grep rpm"
    rpm_list = os.popen(cmd).read().split()
    new_rpm_list = [rpm for rpm in rpm_list if rpm != '']
    if new_rpm_list:
        pkg_rpm_list.extend(new_rpm_list)

def get_release_all_pkg_rpms(release_pkg_list):
    """
    get rpms of all pkg
    """
    pkg_rpm_list = []
    cmd = "arch"
    arch = os.popen(cmd).read().strip()
    with ThreadPoolExecutor(100) as executor:
        for pkg in release_pkg_list:
            executor.submit(get_pkg_rpms, pkg, arch, pkg_rpm_list)
    return pkg_rpm_list 

def delete_exclude_rpm(not_in_repo_rpm):
    """
    delete exclude rpm
    """
    final_rpm = []
    if not args.project.endswith(":Epol"):
        exclude_rpmlist = get_exclude_rpm_list()
        if exclude_rpmlist:
            for repo_rpm in not_in_repo_rpm:
                rpm_name = repo_rpm.rsplit("-", 2)[0]
                if rpm_name not in exclude_rpmlist:
                    final_rpm.append(repo_rpm)
    else:
        final_rpm = not_in_repo_rpm
    return final_rpm

def write_file(result):
    if os.path.exists(args.logfile):
        with open(args.logfile, "w") as f:
            for line in result:
                f.write(line)
                f.write("\n")

def check_repo_complete():
    """
    check project all pkg rpm equal repo all rpm
    """
    print("========== start check release package rpm in repo ==========")
    release_pkg_list = get_release_pkg_list()
    all_pkg_rpm_list = get_release_all_pkg_rpms(release_pkg_list)
    print("all_pkg_rpm_list:%s" % all_pkg_rpm_list)
    repo_rpm_list = get_repo_rpm_list()
    print("repo_rpm_list:%s" % repo_rpm_list)
    not_in_repo_rpm = list(set(all_pkg_rpm_list) - set(repo_rpm_list))
    if not_in_repo_rpm:
        final_result = delete_exclude_rpm(not_in_repo_rpm)
        print("[FAILED] some package rpm not in repo without exclude rpm")
        if final_result:
            write_file(final_result)
            print("\n".join(final_result))
    else:
        print("[SUCCESS] all package rpm in repo")
    print("========== end check release package rpm in repo ==========")


check_repo_complete()
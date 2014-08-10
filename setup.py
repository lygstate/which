#!/usr/bin/env python
# See LICENSE.txt for license details.
# Author: Yonggang Luo(luoyonggang@gmail.com)
#         Trent Mick(TrentM@ActiveState.com)

"""Distutils setup script for 'which'."""

import os
import re
import shutil
import subprocess
import sys
import tempfile

from distutils.core import setup
from distutils.command.build import build

try:
    import _winreg as winreg
except ImportError:
    try:
        import winreg
    except ImportError:
        winreg = None

all_msvc_platforms = [ ('x64', 'amd64'), ('x86', 'x86'), ('ia64', 'ia64'), ('x86_amd64', 'amd64'), ('x86_ia64', 'ia64'), ('x86_arm', 'arm') ]
"""List of msvc platforms"""

def GetCompilerEnvironment(compiler, target, vcvars):
    tempFile = tempfile.NamedTemporaryFile(suffix=".bat", delete=False)
    tempFile.write(
        '''@echo off
        set INCLUDE=
        set LIB=
        set LIBPATH=
        call "%s" %s
        @echo TEST_COMPILER_PATH=%%PATH%%
        @echo TEST_COMPILER_INCLUDE=%%INCLUDE%%
        @echo TEST_COMPILER_LIB=%%LIB%%;%%LIBPATH%%
        for /f "delims=" %%%%a in ('@where %s') do @echo TEST_COMPILER_EXE=%%%%a
        ''' %(vcvars, target, compiler)
    )
    tempFile.close()
    cmd = [tempFile.name]
    p = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)

    out,err = p.communicate()
    if not out:
        return None,None
    ms = {}
    for p in [i for i in os.environ['PATH'].split(';') if i]:
        if not p in ms:
            ms[p] = 0
        ms[p] = ms[p] - 1
    MSVC_PATH = MSVC_INCDIR = MSVC_LIBDIR = []
    MSVC_COMPILER = []
    for line in out.splitlines():
        if line.startswith('TEST_COMPILER_PATH='):
            pathList = [i for i in line[len('TEST_COMPILER_PATH='):].split(';') if i]
            for p in pathList:
                if not p in ms:
                    ms[p] = 0
                ms[p] = ms[p] + 1
            for p in pathList:
                if ms[p] > 0:
                    MSVC_PATH.append(p)
                    ms[p] = 0
        elif line.startswith('TEST_COMPILER_INCLUDE='):
            MSVC_INCDIR = [i for i in line[len('TEST_COMPILER_INCLUDE='):].split(';') if i]
        elif line.startswith('TEST_COMPILER_LIB='):
            MSVC_LIBDIR = [i for i in line[len('TEST_COMPILER_LIB='):].split(';') if i]
        elif line.startswith('TEST_COMPILER_EXE='):
            MSVC_COMPILER.append(line[len('TEST_COMPILER_EXE='):])
    if [] in (MSVC_INCDIR, MSVC_LIBDIR,MSVC_COMPILER):
        return None,None,None,None
    return MSVC_COMPILER[0], MSVC_PATH, MSVC_INCDIR, MSVC_LIBDIR

def GetMsvcTargets(version, vc_path):
    msvcTargetList = []
    vcVarList = [
        (os.path.join(vc_path, 'vcvarsall.bat'),all_msvc_platforms[::-1]),
        (os.path.join(vc_path, 'Common7', 'Tools', 'vsvars32.bat'),[('x86', 'x86')]),
        (os.path.join(vc_path, 'Bin', 'vcvars32.bat'),[('x86', 'x86')]),
    ]
    for vcVarFile, targetList in vcVarList:
        if not os.path.exists(vcVarFile):
            continue
        for target,realtarget in targetList:
            compiler,path,incdir,libdir = GetCompilerEnvironment('cl', target, vcVarFile)
            if compiler:
                msvcTargetList.append( ('msvc', version, target, realtarget, compiler, path, incdir, libdir) )
        break;
    return msvcTargetList

def GetCompier():
    #Detected MSVC versions!
    version_pattern = re.compile('^(\d\d?\.\d\d?)(Exp)?$')
    detected_versions = []
    for vcver,vcvar in (('VCExpress','Exp'), ('VisualStudio','')):
        try:
            prefix = 'SOFTWARE\\Wow6432node\\Microsoft\\'+vcver
            all_versions = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, prefix)
        except WindowsError:
            try:
                prefix = 'SOFTWARE\\Microsoft\\'+vcver
                all_versions = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, prefix)
            except WindowsError:
                continue
        index = 0
        while True:
            try:
                version = winreg.EnumKey(all_versions, index)
            except WindowsError:
                break
            index = index + 1
            match = version_pattern.match(version)
            if not match:
                continue
            else:
                versionnumber = float(match.group(1))
            detected_versions.append((versionnumber, version+vcvar, prefix+"\\"+version))
        pass

    def versionKey(tup):
        return tup[0]

    detected_versions.sort(key = versionKey)

    vc_paths = []
    for (v,version,reg) in detected_versions:
        try:
            try:
                msvc_version = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg + "\\Setup\\VC")
            except WindowsError:
                msvc_version = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg + "\\Setup\\Microsoft Visual C++")
            path,type = winreg.QueryValueEx(msvc_version, 'ProductDir')
            vc_paths.append((version, os.path.abspath(str(path))))
        except WindowsError:
            continue
    msvcTargetList = []
    for vcVersion, vcPath in vc_paths:
        msvcTargetList += GetMsvcTargets(vcVersion, vcPath)
    retTarget = None
    for target in msvcTargetList:
        if (target[3] == 'x86'):
            retTarget = target
    return retTarget

class BuildExecutable(build):
    def run(self):
        outPath = os.path.abspath(self.build_lib)
        inPath = os.path.dirname(__file__)
        if not os.path.exists(outPath):
            os.makedirs(outPath)
        compiler = GetCompier()
        cmds = [compiler[4],
            '-D_CONSOLE',
            '-D_MBCS',
            '-DWIN32',
            '-W3',
            '-Ox',
            '-DNDEBUG',
            '-D_NDEBUG',
            '-MT',
            '-wd4996',
            #'-Ze', this is for vs 2005 and lower
            '/Zc:forScope-',
            os.path.join(inPath, 'launcher.cpp'),
            '/Fo%s' % os.path.join(outPath, 'launcher.obj'),
            '/link',
            '/OUT:%s' % os.path.join(inPath, 'which.exe'),
            '/subsystem:console',
            'kernel32.lib',
            'user32.lib',
            'gdi32.lib',
            'advapi32.lib',
            'shlwapi.lib'
        ]
        env = dict(os.environ)
        env['PATH'] = ';'.join(compiler[5]) + ';' + env['PATH']
        env['INCLUDE'] = ';'.join(compiler[6])
        env['LIB'] = ';'.join(compiler[7])
        p = subprocess.Popen(cmds, env=env, shell=False)
        p.wait()
        os.remove(os.path.join(outPath, 'launcher.obj'))
        build.run(self)

    def get_outputs(self):
        ret = build.get_outputs(self)
        return ret

#---- support routines

def _getVersion():
    import which
    return which.__version__

#---- setup mainline

if sys.platform == "win32":
    scripts = []
    binFiles = ["which.exe", "which.py"]
else:
    # Disable installing which as a script on non-Windows platforms.
    # Other system has already have a which
    binFiles = []
    scripts = []

setup(name="which",
      version=_getVersion(),
      description="a portable GNU `which` replacement",
      author="Yonggang Luo;Trent Mick",
      author_email="luoyonggang@gmail.com",
      url="http://github.com/lygstate/which/",
      license="MIT License",
      platforms=["Windows", "Linux", "Mac OS X", "Unix"],
      long_description="""\
This is a GNU which replacement with the following features:
    - it is portable (Windows, Linux);
    - it understands PATHEXT on Windows;
    - it can print <em>all</em> matches on the PATH;
    - it can note "near misses" on the PATH (e.g. files that match but
      may not, say, have execute permissions; and
    - it can be used as a Python module.
""",
      keywords=["which", "find", "path", "where"],

      py_modules=['which'],
      scripts=scripts,
      # Install the Windows which.exe inside both $PYTHON_DIR and 
      # $PYTHON_DIR\Scripts, so whenever how the path is setting,
      # the which script always works
      data_files=[('', binFiles), ('Scripts', binFiles)],
      cmdclass={'build': BuildExecutable},
     )


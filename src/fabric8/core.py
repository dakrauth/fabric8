import io
import getpass
from pathlib import Path

import fabric
from invoke import collection
import invoke.tasks
from dotenv import dotenv_values

from . import utils


class Collection(collection.Collection):
    def register_task(self, fn):
        self.add_task(invoke.tasks.task(fn))
        return fn

    def add_module(self, mod):
        coll = collection.Collection.from_module(mod)
        self.add_collection(coll)


class RemoteCommand:
    base_cmd = ""

    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def run(self, *commands, **kwargs):
        results = []
        for cmd in commands:
            if self.base_cmd:
                cmd = f"{self.base_cmd} {cmd}"

            result = self.conn.run(f"{cmd}", **kwargs)
            utils.debug(result.command)
            results.append(result)

        return results[0] if len(commands) == 1 else results


class RemotePython(RemoteCommand):
    def __init__(self, conn, site):
        super().__init__(conn)
        self.site = site
        self.base_cmd = f"{site.venv}/bin/python"
    
    def pip(self, pip_cmd):
        self.run(f"-m pip {pip_cmd}")


class RemoteDjango(RemotePython):
    def __init__(self, conn, site):
        super().__init__(conn, site)
        self.base_cmd = f"DJANGO_SETTINGS_MODULE={site.settings} {self.base_cmd} manage.py"

    def run(self, *commands, **kwargs):
        with self.conn.cd(self.site.project.path):
            return super().run(*commands, **kwargs)


class Project:
    def __init__(self, name, path):
        self.name = name
        self.path = Path(path)

    def __str__(self):
        return f"{self.__class__.__name__} {self.name}: {self.path}"


class Repo(Project):
    def __init__(self, name, path, branch):
        super().__init__(name, path)
        self.branch = branch


class RemoteGit(RemoteCommand):
    base_cmd = "git"

    def __init__(self, conn, repo):
        assert isinstance(repo, Repo) is True, "repo object must be instance of Repo"
        super().__init__(conn)
        self.repo = repo

    def run(self, *commands, **kwargs):
        with self.conn.cd(self.repo.path):
            return super().run(*commands, **kwargs)

    def pull(self, **kwargs):
        print(f"Pulling {self.repo.path}...")
        self.run("fetch", "reset --hard HEAD", "pull --rebase=true", **kwargs)

    def current_branch(self):
        return self.run("branch --show-current", hide="out").stdout.strip()

    def status(self):
        r = self.run("status --porcelain")
        return r.stdout

    def update(self, reset=False):
        current_branch = self.current_branch()
        if current_branch != self.repo.branch:
            utils.error(f"Aborting: current branch ({current_branch}) not {self.repo.branch}")
            return False

        status = [line for line in self.status().splitlines() if not line.startswith("?? ")]
        if status and not reset:
            utils.error(f"Aborting: modified files")
            return False

        self.pull()
        return True


class Site:
    def __init__(self, conn, name, attrs):
        self.conn = conn
        self.name = name
        self._attrs = attrs
        self.repo = Repo(name, attrs.repo, attrs.branch)
        self.project = Project(name, attrs.project) if "project" in attrs else self.repo
        self.extras = {}
        for key in getattr(attrs, "extras", {}):
            value = attrs.extras[key]
            self.extras[key] = Repo(key, value.repo, value.branch)

    def __getattr__(self, name):
        return self._attrs.get(name)

    @property
    def env_path(self):
        return self.repo.path / self._attrs.env

    def repos(self, extras=True):
        yield self.repo
        if extras:
            for extra in self.extras.values():
                yield extra

    @property
    def env_dict(self):
        text_io = self.conn.remote_io(self.env_path)
        return dotenv_values(stream=text_io)

    def save_env(self, dct, version=None):
        version = version or utils.version_timestamp()
        fn = self.env_path
        self.conn.run(f"cp {fn} {fn}.{version}.bak")

        text_io = io.StringIO()
        for key in sorted(dct):
            val = dct[key]
            text_io.write(f"{key}={val}\n")

        print("=== Before ===")
        self.conn.run(f"cat {fn}")

        self.conn.put(io.StringIO(text_io.getvalue()), str(fn))
        print("=== After ===")
        self.conn.run(f"cat {fn}")


class GroupedConnection(fabric.Connection):
    group_name = None

    def __init__(self, group_name, *args, **kwargs):
        self.group_name = group_name
        super().__init__(*args, **kwargs)
        self._history = []
        self._fabric8 = self.config.fabric8
        self._group = self._fabric8.groups[self.group_name]
        self._sites = {
            name: Site(self, name, self._fabric8.sites[name])
            for name in self._group.sites
        }
        default_site = self._group.get("default", self._group.sites[0])
        self._default_site = self._sites[default_site]
        if kwargs.get("password") is True:
            self.getpass()

    def history(self, result):
        self._history.append(result.command)

    def run(self, command, **kwargs):
        utils.log(f"🔹 {command}")
        result = super().run(command, **kwargs)
        self.history(result)
        return result

    def local(self, *args, **kwargs):
        result = super().local(*args, **kwargs)
        self.history(result)
        return result

    def getpass(self):
        if self.config.sudo.password is None:
            self.config.sudo.password = getpass.getpass("Sudo password> ")

    def sudo(self, command, **kwargs):
        self.getpass()
        kwargs["password"] = self.config.sudo.password
        kwargs.setdefault("hide", "stderr")
        utils.log(f"🔓 {command}")
        result = super().sudo(command, **kwargs)
        self.history(result)
        return result

    def remote_io(self, remote_path, text=True):
        bytes_io = io.BytesIO()
        result = self.get(remote_path, local=bytes_io)
        return io.StringIO(bytes_io.getvalue().decode()) if text else bytes_io

    def as_user(self, user, cmd):
        # for instance, conn.as_user("www-data", "whoami")
        self.sudo(f"su - {user} -s /bin/bash -c '{cmd}'")

    def python(self, site=None):
        return RemotePython(self, self.site(site))

    def django(self, site=None):
        return RemoteDjango(self, self.site(site))

    def git(self, repo):
        return RemoteGit(self, repo or self.site().repo)

    def restart(self, service):
        self.sudo(f"systemctl restart {service}")

    def bump_versions(self, sites, attrs="STATIC,MEDIA"):
        ver = utils.version_timestamp()
        for site in self.sites(sites):
            changed = False
            dct = site.env_dict
            for key in [f"{attr}_VERSION" for attr in attrs.split(",")]:
                if key in dct:
                    changed = True
                    dct[key] = ver
                    print(f"{key}={dct[key]}")

            if changed:
                site.save_env(dct, version=ver)

    def sites(self, sites="*"):
        if isinstance(sites, str):
            sites = self._sites.keys() if sites.upper() in ["ALL", "*"] else sites.split(",")
        for s in sites:
            site = self.site(s)
            utils.banner(f"Site: {site.name}", level=0)
            yield site

    def site(self, site=None):
        if isinstance(site, Site):
            return site
 
        return self._sites[site] if site else self._default_site

    def repos(self, sites=None, extras=True):
        seen = set()
        for site in self.sites(sites):
            for repo in site.repos(extras):
                if repo.path in seen:
                    continue

                seen.add(repo.path)
                yield repo


def task_group(group_name):

    class GroupTask(fabric.Task):
        def __call__(self, ctx, *args, **kwargs):
            conn = GroupedConnection(group_name, ctx.host, config=fabric.Config(defaults=ctx))
            return super().__call__(conn, *args, **kwargs)

    def task(*args, **kwargs):
        kwargs.setdefault("klass", GroupTask)
        return fabric.task(*args, **kwargs)

    return task

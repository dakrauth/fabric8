import json
from . import utils


def run(conn, cmd):
    conn.run(cmd)


def info(conn, sites, lines=1):
    for repo in conn.repos(sites):
        utils.banner(f"{repo}")
        git = conn.git(repo)
        r = git.run("status --porcelain")
        if not r.stdout:
            print("<up to date>")

        git.run(f"log -{lines} --pretty=tformat:'%h %s | %ci (%cr)'")


def system(conn, cmd):
    conn.sudo(f"systemctl {cmd}")


def sys_restart(conn, services):
    for svc in services.split(","):
        conn.sudo(f"systemctl restart {svc}")


def migrations(conn, sites, args=""):
    for site in conn.sites(sites):
        dj = conn.django(site)
        r = dj.run(f"showmigrations {args}")


def pip(conn, cmd="list"):
    conn.python().run(f"-m pip {cmd}")


def bump(conn, sites, attrs="STATIC,MEDIA"):
    conn.bump_versions(sites, attrs)


def env(conn, sites):
    for site in conn.sites(sites):
        with conn.cd(site.repo.path):
            utils.banner(f"ENV for {site.name}")
            conn.run(f"cat {site.env} | sort")
            print()


def execfile(conn, filename, site=None):
    dj = conn.django(site)
    dj.run(f"execfile {filename}")


def deploy(conn, sites, reset=False, nginx=False, migrate="", bump=False, extras=True):
    """
    <sites> - a comma delimited list of sites, should be either comma-delimited <site>'s, ALL (or *)
    <reset> - if true, a hard git reset will be done in the repo if modified, otherwise abort
    <nginx> - if true, restart nginx
    <migrate> - a comma delimited list of apps to migrate
    <bump> - if true, bump STATIC_VERSION and MEDIA_VERSION if found in site .env file
    <extras> - if true, update sites' extra repos

    Example:

        fab nf.deploy picks --bump
    """
    for repo in conn.repos(sites, extras):
        git = conn.git(repo)
        if not git.update(reset):
            print(f"Default git repo {repo.name} not updated")
            return

    if migrate:
        if migrate == "ALL":
            conn.django().run("migrate")
        elif migrate == "PAUSE":
            utils.wait_for("Y")
        else:
            for m in migrate.split(","):
                conn.django().run(f"migrate {m}")

    if bump:
        conn.bump_versions(sites)

    for site in conn.sites(sites):
        print(f"Restarting {site.gunicorn}...")
        conn.sudo(f"systemctl restart {site.gunicorn}")

    if nginx:
        conn.sudo(f"systemctl restart nginx")


def compare(conn):
    results = {}
    loc = json.loads(conn.local("pip list --format json").stdout)

    s = conn.python("ftl").run(f"-m pip list --format json").stdout
    rem = json.loads(s)
    for name, data in [("local", loc), ("remote", rem)]:
        for dep in data:
            results.setdefault(dep["name"], {})[name] = dep["version"]

    with open("compare.json", "w") as fp:
        fp.write(json.dumps(results, indent=4))



def quick(conn, site, bump=True):
    """
    <sites> - a comma delimited list of sites, should be either comma-delimited <site>'s, ALL (or *)
    <bump> - if true, bump STATIC_VERSION and MEDIA_VERSION if found in site .env file

    Example:

        fab nf.quick picks --bump
    """
    site = conn.site(site)
    repo = next(site.repos(False))
    git = conn.git(repo)
    if not git.update(False):
        print(f"Default git repo {repo.name} not updated")
        return

    if bump:
        conn.bump_versions([site], "STATIC,MEDIA")

    print(f"Restarting {site.gunicorn}...")
    conn.sudo(f"systemctl restart {site.gunicorn}")

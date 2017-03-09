postgres-ha
===========

With this role, you will transform your standalone postgresql server to N-node postgres cluster with automated failover. You only need one working postgresql server and other hosts with clean CentOS 7 minimal install.

What it will do:
- install the cluster software stack (pcs, corosync, pacemaker)
- add cluster hosts IPs to /etc/hosts file
- create cluster from all play hosts
- install database binaries if needed
- alter postgres settings if needed
- sync slave databases from master host
- make sure the DB replication is working
- create database and IP resources and constraints
- check again that everything is working as expected

Automated failover is setup using PAF pacemaker module: https://github.com/dalibo/PAF

What you should know
--------------------

The role is idempotent. I've made many checks to allow running it multiple times without breaking things. You can run it again safely even if the role fails. The only thing you need to check before the run is the `postgres_ha_cluster_master_host` variable. But don't worry, if the specified host is not the master database, the role will fail gracefully without disrupting things.

During the run, the role will alter your postgresql.conf and pg_hba.conf to enable replication. You can review the changes to postgresql.conf in defaults/main.yml (`postgres_ha_postgresql_conf_vars` parameter). In pg_hba.conf, the host ACL statements will be added for every cluster node. They will be added before all previously existing host ACL statements.

You should have at least a basic understanding of clustering and how to work with `pcs` command. If the role fails for some reason, it is relatively easy to recover from it.. if you understand what logs are trying to say and/or how to run appropriate recovery actions. See cleanup section for more info.

You need to alter firewall settings before running this role. The cluster members need to communicate among each other to form a cluster and to replicate postgres DB. I recommend adding some firewall role before the postgres-ha role.

If the master datadir is empty, the role will init an empty datadir. Slave nodes will then download this empty database. If the datadir is not empty, the initdb will be skipped. This means that you can run this role on clean CentOS installs that does not have any postgresql database installed. The result will be fully working empty database cluster.

On the first run, the datadirs on slave nodes will be deleted without prompt. Please make sure you specify the correct `postgres_ha_cluster_master_host` at least for this first run (slave datadirs will NEVER be deleted after first initial sync is done).

If you plan to apply the role to higher number of servers (7+) please be aware that the servers are downloading rpms packages simultaneously. This can be identified as DDoS and some repository providers may refuse your downloads. As a result, the role will fail. I recommend setting up your own repository mirror in such cases.

Please don't change the cluster resource name parameters after the role has been applied. In next run, it will result in trying to create the new colliding resources.

Requirements
------------

The postgresql binaries on primary server should be installed from official repository here: https://yum.postgresql.org/repopackages.php
If it's not, you need to edit the `postgresql_sync.yml` task link to change postgres repo rpm and package names. And maybe also bindir and datadir paths in role variables.

Please note that fencing is not configured in this role. If you need one, you have to configure it manually after running this role.

Role Variables
--------------

See defaults in defaults/main.yml

Variables that must be changed:
- `postgres_ha_cluster_master_host`		-	the master database host (WARNING: please make sure you fill this correctly, otherwise you may lose data!)
- `postgres_ha_cluster_vip`				-	a floating IP address that travels with master database
- `postgres_ha_pg_repl_pass`			-	password for replicating postgresql data
- `postgres_ha_cluster_ha_password`		-	password for cluster config replication
- `postgres_ha_cluster_ha_password_hash`-	password hash of postgres_ha_cluster_ha_password

Password hash can be generated for example by this command:
`python -c 'import crypt; print(crypt.crypt("my_cluster_ha_password", crypt.mksalt(crypt.METHOD_SHA512)))'`

Dependencies
------------

No other roles are required as a dependency. However you can combine this role with some other role that installs a postgresql database.

Example Playbook
----------------

The usage is relatively simple - install minimal CentOS-es, set the variables and run the role.
Two settings are required:
`gather_facts=True`		- we need to know the IP addresses of cluster nodes
`any_errors_fatal=True`	- it ensures that error on any node will result in stopping the whole ansible run. Because it doesn't make sense to continue when you lose some of your cluster nodes during transit.

    - name: install PG HA
	  hosts: db?
	  gather_facts: True
	  any_errors_fatal: True
	  vars:
	    postgres_ha_cluster_master_host: db1
	  	postgres_ha_cluster_vip: 10.100.200.50
		postgres_ha_pg_repl_pass: MySuperSecretDBPass
		postgres_ha_cluster_ha_password: AnotherSuperSecretPass1234
		postgres_ha_cluster_ha_password_hash: '$6$mHeZ7/LD1y.........7VJYu.'
      roles:
         - postgres-ha


Cleanup after failure
---------------------

If the role fails repeatedly and you want to run it fresh as if it was the first time, you need to clean up some things.
Please note that I use default resource names. If you change them using variables, you need to change it also in these commands.

- RUN ON ANY NODE:
```
pcs resource delete pg-vip
pcs resource delete postgres
#pcs resource delete postgres-ha   # probably not needed
#pcs resource cleanup postgres     # probably not needed

# Make sure no (related) cluster resources are defined.
```
- RUN ON ALL SLAVE NODES:
```
systemctl stop postgresql-9.6
# Make sure no postgres db is running.
systemctl status postgresql-9.6
ps aux | grep postgres
rm -rf /var/lib/pgsql/9.6/data
rm -f /var/lib/pgsql/9.6/recovery.conf.pgcluster.pcmk
rm -f /root/.constraints_processed
```
- RUN ONLY ON MASTER NODE:
```
systemctl stop postgresql-9.6
rm -f /var/lib/pgsql/9.6/recovery.conf.pgcluster.pcmk
rm -f /var/lib/pgsql/9.6/data/recovery.conf
rm -f /var/lib/pgsql/9.6/data/.synchronized
rm -f /root/.constraints_processed
# Make sure no postgres db is running.
ps aux | grep postgres
systemctl start postgresql-9.6
systemctl status postgresql-9.6
# Check postgres db functionality.
```
- START AGAIN
Check variables & defaults and run ansible role again.


License
-------

BSD

Author Information
------------------

Created by YanChi.
Originally part of the Danube Cloud project (https://github.com/erigones/esdc-ce).


# reverse-ssh

Keeps a persistent reverse SSH tunnel from the device to a server you own, so
you can reach a box behind NAT with `ssh -p <port> user@localhost` on that
server. Needs `vars.reverse_ssh_host`, `reverse_ssh_user`, `reverse_ssh_port`,
and the device user's SSH key authorized on the server (put a key in
`identity.ssh_keys` and copy the private half after install, or use the
`webhook` preset to collect the device's generated key).

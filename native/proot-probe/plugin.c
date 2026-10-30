/* SPDX-License-Identifier: GPL-3.0-only */
/* Real dynamically loaded code with independent per-thread TLS state. */
static __thread int value = 41;
int esteria_probe_tls(void) { return ++value; }

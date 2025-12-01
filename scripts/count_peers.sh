#!/bin/sh

find group_vars/dn42/peers -type f -print0 | xargs -0 grep -h "asn:" | awk '{print $2}' | sort | uniq | wc -l

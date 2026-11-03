// Test-only annotation declaration; no parsing/quoting behavior is replaced.
package android.annotation; public @interface SystemApi { Client client() default Client.PRIVILEGED_APPS; enum Client { PRIVILEGED_APPS, MODULE_LIBRARIES } }

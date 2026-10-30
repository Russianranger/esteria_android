# Included from the existing root CMAKE_PROJECT_INCLUDE reference setup.
# This does not alter the pinned source tree or enable a module that is absent.
function(esteria_add_playerbots_database_reference)
    if(NOT TARGET database OR NOT TARGET acore-core-interface)
        message(FATAL_ERROR "The playerbots reference requires the real server database target")
    endif()
    get_target_property(esteria_database_options database COMPILE_OPTIONS)
    if(NOT "-DMOD_PLAYERBOTS" IN_LIST esteria_database_options)
        message(FATAL_ERROR "The actual database target was not configured with MOD_PLAYERBOTS")
    endif()
    add_executable(esteria_playerbots_database_reference EXCLUDE_FROM_ALL
        "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/playerbots_database_reference.cpp")
    target_compile_features(esteria_playerbots_database_reference PRIVATE cxx_std_20)
    target_compile_definitions(esteria_playerbots_database_reference PRIVATE MOD_PLAYERBOTS)
    target_link_libraries(esteria_playerbots_database_reference PRIVATE database acore-core-interface)
endfunction()

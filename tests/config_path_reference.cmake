# Actual ConfigMgr/common target; no parser or logging replacements.
if(PROJECT_NAME STREQUAL "AzerothCore" AND CMAKE_CURRENT_SOURCE_DIR STREQUAL CMAKE_SOURCE_DIR)
    function(esteria_add_config_path_reference)
        if(NOT TARGET common)
            message(FATAL_ERROR "The module configuration reference requires the real common target")
        endif()
        add_executable(esteria_config_path_reference EXCLUDE_FROM_ALL
            "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/config_path_reference.cpp")
        target_compile_features(esteria_config_path_reference PRIVATE cxx_std_20)
        target_link_libraries(esteria_config_path_reference PRIVATE common)
    endfunction()
    cmake_language(DEFER CALL esteria_add_config_path_reference)
endif()

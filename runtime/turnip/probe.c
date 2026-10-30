/* SPDX-License-Identifier: GPL-3.0-only */
/* Bounded real Turnip shader/raster/readback probe. No window or game claims. */
#define _GNU_SOURCE
#include <vulkan/vulkan.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "probe_shaders.h"

static void require(int ok, const char *reason) {
    if (!ok) { fprintf(stderr, "Turnip probe failed: %s\n", reason); exit(70); }
}
static void checked(VkResult result, const char *reason) {
    if (result != VK_SUCCESS) {
        fprintf(stderr, "Turnip probe failed: %s (VkResult=%d)\n", reason, result); exit(70);
    }
}
static uint32_t memory_type(VkPhysicalDevice gpu, uint32_t allowed, VkMemoryPropertyFlags flags) {
    VkPhysicalDeviceMemoryProperties properties; vkGetPhysicalDeviceMemoryProperties(gpu, &properties);
    for (uint32_t i = 0; i < properties.memoryTypeCount; ++i)
        if ((allowed & (1u << i)) && (properties.memoryTypes[i].propertyFlags & flags) == flags) return i;
    require(0, "required memory type unavailable"); return 0;
}
static VkDeviceMemory allocate(VkPhysicalDevice gpu, VkDevice device, VkMemoryRequirements requirements,
                               VkMemoryPropertyFlags flags) {
    VkMemoryAllocateInfo info = {.sType=VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
        .allocationSize=requirements.size, .memoryTypeIndex=memory_type(gpu, requirements.memoryTypeBits, flags)};
    VkDeviceMemory memory; checked(vkAllocateMemory(device, &info, NULL, &memory), "allocate actual GPU memory");return memory;
}
static void receipt(const char *path, int hardware, const VkPhysicalDeviceProperties *properties) {
    int fd = open(path, O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW, 0600);
    require(fd >= 0, "exclusive receipt creation"); FILE *file = fdopen(fd, "w"); require(file != NULL, "receipt stream");
    fprintf(file, "{\"formatVersion\":1,\"scope\":\"linux-arm64-turnip-kgsl-component-probe\","
        "\"icdLoaded\":true,\"noKgslHostVerified\":%s,\"turnip740ShaderReadbackQualified\":%s,"
        "\"pixelsVerified\":%u,\"vendorId\":%u,\"deviceId\":%u,\"deviceName\":\"",
        hardware ? "false" : "true", hardware ? "true" : "false", hardware ? 4096u : 0,
        hardware ? properties->vendorID : 0, hardware ? properties->deviceID : 0);
    if (hardware) for (const unsigned char *p=(const unsigned char *)properties->deviceName; *p; ++p) {
        if (*p < 32 || *p == '\\' || *p == '"' || *p >= 127) fprintf(file, "\\u%04x", *p);
        else fputc(*p, file);
    }
    fputs("\",\"x11PresentationQualified\":false,\"androidQualified\":false,\"gameplayQualified\":false}\n", file);
    require(!ferror(file) && fflush(file) == 0 && fsync(fd) == 0, "receipt persistence");
    require(fclose(file) == 0, "receipt close");
}
int main(int argc, char **argv) {
#if !defined(__aarch64__)
    require(0, "this artifact qualifies native Linux ARM64 only");
#endif
    require(argc == 4 && (!strcmp(argv[3], "--expect-no-kgsl") || !strcmp(argv[3], "--gpu-readback")),
        "usage: probe exact-driver.so new-receipt.json --expect-no-kgsl|--gpu-readback");
    alarm(25); /* Outer supervisor must also enforce a deadline. */
    const int no_gpu = !strcmp(argv[3], "--expect-no-kgsl");
    struct stat status;
    if (no_gpu) require(lstat("/dev/kgsl-3d0", &status) != 0 && errno == ENOENT, "CI requires absent KGSL, never a physical-device probe");
    else require(stat("/dev/kgsl-3d0", &status) == 0 && S_ISCHR(status.st_mode), "KGSL character device required");
    void *icd = dlopen(argv[1], RTLD_NOW|RTLD_LOCAL);
    require(icd != NULL && dlsym(icd, "vk_icdGetInstanceProcAddr") != NULL, "exact source-built ICD loads and exports loader entrypoint");
    VkApplicationInfo application = {.sType=VK_STRUCTURE_TYPE_APPLICATION_INFO,
        .pApplicationName="Esteria Turnip component probe", .apiVersion=VK_API_VERSION_1_2};
    VkInstanceCreateInfo instance_info = {.sType=VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo=&application};
    VkInstance instance = VK_NULL_HANDLE; VkResult created = vkCreateInstance(&instance_info, NULL, &instance);
    if (no_gpu && created == VK_ERROR_INCOMPATIBLE_DRIVER) {
        require(dlclose(icd) == 0, "ICD unload"); receipt(argv[2], 0, NULL); return 0;
    }
    checked(created, "loader creates real ICD instance");
    uint32_t count = 0; checked(vkEnumeratePhysicalDevices(instance, &count, NULL), "enumerate actual devices");
    if (no_gpu) {
        require(count == 0, "software or unexpected physical device must not qualify no-KGSL check");
        vkDestroyInstance(instance, NULL); require(dlclose(icd) == 0, "ICD unload"); receipt(argv[2], 0, NULL); return 0;
    }
    require(count == 1, "exactly one selected Turnip hardware device required");
    VkPhysicalDevice gpu; checked(vkEnumeratePhysicalDevices(instance, &count, &gpu), "obtain GPU");
    VkPhysicalDeviceDriverProperties driver = {.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES};
    VkPhysicalDeviceProperties2 properties = {.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2, .pNext=&driver};
    vkGetPhysicalDeviceProperties2(gpu, &properties);
    require(strnlen(properties.properties.deviceName, sizeof(properties.properties.deviceName)) < sizeof(properties.properties.deviceName),
        "bounded physical-device name");
    require(properties.properties.vendorID == 0x5143 && properties.properties.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU &&
        driver.driverID == VK_DRIVER_ID_MESA_TURNIP && strstr(properties.properties.deviceName, "740") != NULL,
        "observed Mesa Turnip Adreno740 required; software or other GPUs refused");
    uint32_t families = 0; vkGetPhysicalDeviceQueueFamilyProperties(gpu, &families, NULL);
    require(families > 0 && families <= 64, "queue family bound"); VkQueueFamilyProperties queues[64];
    vkGetPhysicalDeviceQueueFamilyProperties(gpu, &families, queues);
    uint32_t family = 0; while (family < families && !(queues[family].queueFlags & VK_QUEUE_GRAPHICS_BIT)) ++family;
    require(family < families, "real graphics queue required");
    float priority = 1; VkDeviceQueueCreateInfo queue_info = {.sType=VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
        .queueFamilyIndex=family, .queueCount=1, .pQueuePriorities=&priority};
    VkDeviceCreateInfo device_info = {.sType=VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount=1, .pQueueCreateInfos=&queue_info};
    VkDevice device; checked(vkCreateDevice(gpu, &device_info, NULL, &device), "create hardware logical device");
    VkQueue queue; vkGetDeviceQueue(device, family, 0, &queue);
    VkImageCreateInfo image_info = {.sType=VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType=VK_IMAGE_TYPE_2D,
        .format=VK_FORMAT_R8G8B8A8_UNORM, .extent={64,64,1}, .mipLevels=1, .arrayLayers=1,
        .samples=VK_SAMPLE_COUNT_1_BIT, .tiling=VK_IMAGE_TILING_OPTIMAL,
        .usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT, .sharingMode=VK_SHARING_MODE_EXCLUSIVE};
    VkImage image; checked(vkCreateImage(device, &image_info, NULL, &image), "create render image");
    VkMemoryRequirements requirements; vkGetImageMemoryRequirements(device, image, &requirements);
    VkDeviceMemory image_memory=allocate(gpu, device, requirements, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    checked(vkBindImageMemory(device, image, image_memory, 0), "bind render memory");
    VkImageViewCreateInfo view_info = {.sType=VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image=image,
        .viewType=VK_IMAGE_VIEW_TYPE_2D, .format=image_info.format, .subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1}};
    VkImageView view; checked(vkCreateImageView(device, &view_info, NULL, &view), "create image view");
    VkAttachmentDescription attachment = {.format=image_info.format, .samples=VK_SAMPLE_COUNT_1_BIT,
        .loadOp=VK_ATTACHMENT_LOAD_OP_CLEAR, .storeOp=VK_ATTACHMENT_STORE_OP_STORE,
        .stencilLoadOp=VK_ATTACHMENT_LOAD_OP_DONT_CARE, .stencilStoreOp=VK_ATTACHMENT_STORE_OP_DONT_CARE,
        .initialLayout=VK_IMAGE_LAYOUT_UNDEFINED, .finalLayout=VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL};
    VkAttachmentReference reference = {0,VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL};
    VkSubpassDescription subpass = {.pipelineBindPoint=VK_PIPELINE_BIND_POINT_GRAPHICS, .colorAttachmentCount=1, .pColorAttachments=&reference};
    VkSubpassDependency dependency = {.srcSubpass=0, .dstSubpass=VK_SUBPASS_EXTERNAL,
        .srcStageMask=VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT, .dstStageMask=VK_PIPELINE_STAGE_TRANSFER_BIT,
        .srcAccessMask=VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT, .dstAccessMask=VK_ACCESS_TRANSFER_READ_BIT};
    VkRenderPassCreateInfo pass_info = {.sType=VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO, .attachmentCount=1,
        .pAttachments=&attachment, .subpassCount=1, .pSubpasses=&subpass, .dependencyCount=1, .pDependencies=&dependency};
    VkRenderPass pass; checked(vkCreateRenderPass(device, &pass_info, NULL, &pass), "create render pass");
    VkFramebufferCreateInfo framebuffer_info = {.sType=VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO,
        .renderPass=pass, .attachmentCount=1, .pAttachments=&view, .width=64, .height=64, .layers=1};
    VkFramebuffer framebuffer; checked(vkCreateFramebuffer(device, &framebuffer_info, NULL, &framebuffer), "create framebuffer");
    VkShaderModule modules[2];
    VkShaderModuleCreateInfo shader = {.sType=VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize=sizeof(probe_vert), .pCode=probe_vert};
    checked(vkCreateShaderModule(device, &shader, NULL, &modules[0]), "create actual vertex shader");
    shader.codeSize=sizeof(probe_frag); shader.pCode=probe_frag;
    checked(vkCreateShaderModule(device, &shader, NULL, &modules[1]), "create actual fragment shader");
    VkPipelineShaderStageCreateInfo stages[2] = {
        {.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_VERTEX_BIT,.module=modules[0],.pName="main"},
        {.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_FRAGMENT_BIT,.module=modules[1],.pName="main"}};
    VkPipelineVertexInputStateCreateInfo vertex = {.sType=VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};
    VkPipelineInputAssemblyStateCreateInfo assembly = {.sType=VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO,.topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST};
    VkViewport viewport = {0,0,64,64,0,1}; VkRect2D scissor = {{0,0},{64,64}};
    VkPipelineViewportStateCreateInfo viewport_info = {.sType=VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO,.viewportCount=1,.pViewports=&viewport,.scissorCount=1,.pScissors=&scissor};
    VkPipelineRasterizationStateCreateInfo raster = {.sType=VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO,.polygonMode=VK_POLYGON_MODE_FILL,.cullMode=VK_CULL_MODE_NONE,.lineWidth=1};
    VkPipelineMultisampleStateCreateInfo multisample = {.sType=VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO,.rasterizationSamples=VK_SAMPLE_COUNT_1_BIT};
    VkPipelineColorBlendAttachmentState blend_attachment = {.colorWriteMask=15};
    VkPipelineColorBlendStateCreateInfo blend = {.sType=VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,.attachmentCount=1,.pAttachments=&blend_attachment};
    VkPipelineLayoutCreateInfo layout_info = {.sType=VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    VkPipelineLayout layout; checked(vkCreatePipelineLayout(device,&layout_info,NULL,&layout),"create pipeline layout");
    VkGraphicsPipelineCreateInfo pipeline_info = {.sType=VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO,.stageCount=2,.pStages=stages,
        .pVertexInputState=&vertex,.pInputAssemblyState=&assembly,.pViewportState=&viewport_info,.pRasterizationState=&raster,
        .pMultisampleState=&multisample,.pColorBlendState=&blend,.layout=layout,.renderPass=pass};
    VkPipeline pipeline; checked(vkCreateGraphicsPipelines(device,VK_NULL_HANDLE,1,&pipeline_info,NULL,&pipeline),"compile hardware graphics pipeline");
    VkBufferCreateInfo buffer_info = {.sType=VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,.size=64*64*4,.usage=VK_BUFFER_USAGE_TRANSFER_DST_BIT};
    VkBuffer buffer; checked(vkCreateBuffer(device,&buffer_info,NULL,&buffer),"create readback buffer");
    vkGetBufferMemoryRequirements(device,buffer,&requirements);
    VkDeviceMemory buffer_memory=allocate(gpu,device,requirements,VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT);
    checked(vkBindBufferMemory(device,buffer,buffer_memory,0),"bind readback buffer");
    VkCommandPoolCreateInfo pool_info={.sType=VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,.queueFamilyIndex=family};
    VkCommandPool pool;checked(vkCreateCommandPool(device,&pool_info,NULL,&pool),"create command pool");
    VkCommandBufferAllocateInfo command_info={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=pool,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};
    VkCommandBuffer command;checked(vkAllocateCommandBuffers(device,&command_info,&command),"allocate commands");
    VkCommandBufferBeginInfo begin={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,.flags=VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT};
    checked(vkBeginCommandBuffer(command,&begin),"begin commands");
    VkClearValue clear={.color={{1,0,0,1}}};
    VkRenderPassBeginInfo render={.sType=VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,.renderPass=pass,.framebuffer=framebuffer,.renderArea=scissor,.clearValueCount=1,.pClearValues=&clear};
    vkCmdBeginRenderPass(command,&render,VK_SUBPASS_CONTENTS_INLINE);vkCmdBindPipeline(command,VK_PIPELINE_BIND_POINT_GRAPHICS,pipeline);
    vkCmdDraw(command,3,1,0,0);vkCmdEndRenderPass(command);
    VkBufferImageCopy copy={.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1},.imageExtent={64,64,1}};
    vkCmdCopyImageToBuffer(command,image,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,buffer,1,&copy);
    VkBufferMemoryBarrier barrier={.sType=VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT,.dstAccessMask=VK_ACCESS_HOST_READ_BIT,
        .srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.buffer=buffer,.size=VK_WHOLE_SIZE};
    vkCmdPipelineBarrier(command,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,0,NULL,1,&barrier,0,NULL);
    checked(vkEndCommandBuffer(command),"end commands");
    VkFenceCreateInfo fence_info={.sType=VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};VkFence fence;
    checked(vkCreateFence(device,&fence_info,NULL,&fence),"create completion fence");
    VkSubmitInfo submit={.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&command};
    checked(vkQueueSubmit(queue,1,&submit,fence),"submit real GPU draw");
    checked(vkWaitForFences(device,1,&fence,VK_TRUE,5000000000ULL),"bounded hardware completion");
    void *mapped; checked(vkMapMemory(device,buffer_memory,0,VK_WHOLE_SIZE,0,&mapped),"map readback");
    VkMappedMemoryRange range={.sType=VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE,.memory=buffer_memory,.size=VK_WHOLE_SIZE};
    checked(vkInvalidateMappedMemoryRanges(device,1,&range),"invalidate host readback");
    const unsigned char expected[4]={64,128,191,255};
    for (unsigned i=0;i<64*64*4;++i) require(abs((int)((unsigned char *)mapped)[i]-expected[i%4])<=1,"all4096 shader pixels match");
    vkUnmapMemory(device,buffer_memory);vkDestroyFence(device,fence,NULL);vkDestroyCommandPool(device,pool,NULL);
    vkDestroyBuffer(device,buffer,NULL);vkFreeMemory(device,buffer_memory,NULL);vkDestroyPipeline(device,pipeline,NULL);
    vkDestroyPipelineLayout(device,layout,NULL);for(unsigned i=0;i<2;++i)vkDestroyShaderModule(device,modules[i],NULL);
    vkDestroyFramebuffer(device,framebuffer,NULL);vkDestroyRenderPass(device,pass,NULL);vkDestroyImageView(device,view,NULL);
    vkDestroyImage(device,image,NULL);vkFreeMemory(device,image_memory,NULL);vkDestroyDevice(device,NULL);vkDestroyInstance(instance,NULL);
    require(dlclose(icd)==0,"ICD unload after clean completion");receipt(argv[2],1,&properties.properties);return 0;
}

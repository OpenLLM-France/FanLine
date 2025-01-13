<script lang="ts">
    import { page } from "$app/stores";
    import {
        Sidebar,
        SidebarGroup,
        SidebarItem,
        SidebarWrapper,
        DarkMode,
    } from "flowbite-svelte";
    import { ChartPieSolid, CogSolid } from "flowbite-svelte-icons";
    $: activeUrl = $page.url.pathname;

    let sidebarIconStyle =
        "w-6 h-6 text-gray-500 transition duration-75 dark:text-gray-400 group-hover:text-gray-900 dark:group-hover:text-white";
</script>

<Sidebar {activeUrl} class="h-screen overflow-hidden border-r dark:border-gray-700">
    <SidebarWrapper class="rounded-none p-4"> <!-- Add padding here -->
        <SidebarGroup class="min-h-screen ">
            <SidebarItem label="Dashboard" class="group" href="/admin">
                <svelte:fragment slot="icon">
                    <ChartPieSolid class={sidebarIconStyle} />
                </svelte:fragment>
            </SidebarItem>
            <SidebarItem
                label="Configuration"
                class="group"
                href="/admin/config"
            >
                <svelte:fragment slot="icon">
                    <CogSolid class={sidebarIconStyle} />
                </svelte:fragment>
            </SidebarItem>
            <DarkMode />
        </SidebarGroup>
    </SidebarWrapper>
</Sidebar>



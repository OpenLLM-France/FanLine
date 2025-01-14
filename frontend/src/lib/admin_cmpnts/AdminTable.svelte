<script>
    import {
        Table,
        TableBody,
        TableBodyCell,
        TableBodyRow,
        TableHead,
        TableHeadCell,
    } from "flowbite-svelte";

    export let columns;
    export let data;
    
</script>

{#if data && data.length > 0}
<div class="border border-gray-200 dark:border-gray-700 rounded-lg">
    <Table shadow>
        <TableHead>
            {#each columns as column}
                <TableHeadCell>{column.label}</TableHeadCell>
            {/each}
        </TableHead>
        <TableBody tableBodyClass="divide-y">
            {#each data as row}
                <TableBodyRow>
                    {#each columns as column}
                        <TableBodyCell>{row[column.key]}</TableBodyCell>
                    {/each}
                </TableBodyRow>
            {/each}
        </TableBody>
    </Table>
</div>
{/if}

// Decompile every function that references a string matching any given regex.
// Usage (headless): -postScript DecompileStringRefs.java "<regex>" /path/to/out.c
// @category Analysis
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.StringDataInstance;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import java.io.PrintWriter;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Pattern;

public class DecompileStringRefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Pattern pat = Pattern.compile(args[0]);
        PrintWriter out = new PrintWriter(args[1]);
        Map<Function, String> funcs = new LinkedHashMap<>();
        DataIterator it = currentProgram.getListing().getDefinedData(true);
        while (it.hasNext() && !monitor.isCancelled()) {
            Data d = it.next();
            if (!d.hasStringValue()) continue;
            String s = StringDataInstance.getStringDataInstance(d).getStringValue();
            if (s == null || !pat.matcher(s).find()) continue;
            for (Reference r : getReferencesTo(d.getAddress())) {
                Function f = getFunctionContaining(r.getFromAddress());
                if (f != null) funcs.merge(f, s, (a, b) -> a.contains(b) ? a : a + " | " + b);
            }
        }
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        for (Map.Entry<Function, String> e : funcs.entrySet()) {
            DecompileResults res = di.decompileFunction(e.getKey(), 120, monitor);
            out.println("// ===== " + e.getKey().getName() + " @ " + e.getKey().getEntryPoint() + "  strings: " + e.getValue());
            out.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// decompile failed: " + res.getErrorMessage());
        }
        out.close();
        println("decompiled " + funcs.size() + " functions -> " + args[1]);
    }
}

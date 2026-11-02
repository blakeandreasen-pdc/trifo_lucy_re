// Decompile functions by name (exact or regex) to a C file.
// Usage (headless): -postScript DecompileFunctions.java "<name regex>" /path/to/out.c
// @category Analysis
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import java.io.PrintWriter;
import java.util.regex.Pattern;

public class DecompileFunctions extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Pattern pat = Pattern.compile(args[0]);
        PrintWriter out = new PrintWriter(args[1]);
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        int n = 0;
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            if (!pat.matcher(f.getName()).matches()) continue;
            DecompileResults res = di.decompileFunction(f, 120, monitor);
            out.println("// ===== " + f.getName() + " @ " + f.getEntryPoint());
            out.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// failed: " + res.getErrorMessage());
            n++;
        }
        out.close();
        println("decompiled " + n + " functions -> " + args[1]);
    }
}
